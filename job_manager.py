"""
Job Manager for Background Processing

Manages async jobs for long-running expert calls that would exceed the MCP 60s timeout.
Jobs are stored in-memory and have a maximum lifetime of 24 hours.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import logging


class JobStatus(str, Enum):
    """Status of a background job."""
    PENDING = "pending"        # En file d'attente
    PROCESSING = "processing"  # En cours de traitement
    COMPLETED = "completed"    # Terminé avec succès
    FAILED = "failed"          # Échoué
    TIMEOUT = "timeout"        # Timeout (300s)


@dataclass
class Job:
    """Represents a background job for expert delegation."""
    job_id: str                          # UUID: "job_{uuid.hex[:12]}"
    expert: str                          # "architect", "code_reviewer", etc.
    task: str                            # Description de la tâche
    mode: str                            # "advisory" ou "implementation"
    context: str                         # Contexte fourni
    files: list[str] = field(default_factory=list)  # Liste des fichiers (metadata)
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None         # Résultat (si COMPLETED)
    error: Optional[str] = None          # Message d'erreur (si FAILED/TIMEOUT)
    metadata: dict = field(default_factory=dict)  # {"enhance": bool}

    def to_dict(self) -> dict:
        """Convert job to dictionary for JSON serialization."""
        return {
            "job_id": self.job_id,
            "expert": self.expert,
            "task": self.task[:100] + "..." if len(self.task) > 100 else self.task,
            "mode": self.mode,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "age_seconds": self._age_seconds(),
        }

    def _age_seconds(self) -> float:
        """Calculate job age in seconds."""
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()


class JobManager:
    """
    Manages background jobs for expert delegation.

    Jobs are stored in-memory with automatic cleanup after retention period.
    Maximum concurrent jobs are limited to prevent memory exhaustion.
    """

    def __init__(
        self,
        job_timeout: int = 300,      # 5 min max par job
        max_jobs: int = 100,          # Max jobs simultanés
        retention_hours: int = 24     # Garder résultats 24h
    ):
        self.job_timeout = job_timeout
        self.max_jobs = max_jobs
        self.retention_hours = retention_hours
        self._jobs: dict[str, Job] = {}
        self._events: dict[str, asyncio.Event] = {}  # Notifies waiters on status change
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self.logger = logging.getLogger("llm-delegator.jobs")

    def start(self) -> None:
        """Démarre le cleanup task en arrière-plan."""
        if self._running:
            return
        # Fail-fast if no running event loop
        asyncio.get_running_loop()
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.logger.info("JobManager started")

    async def stop(self) -> None:
        """Arrête le cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self.logger.info("JobManager stopped")

    def generate_job_id(self) -> str:
        """Génère un ID unique pour un job."""
        return f"job_{uuid.uuid4().hex[:12]}"

    async def create_job(
        self,
        expert: str,
        task: str,
        mode: str,
        context: str,
        files: list[str] = None,
        metadata: dict = None
    ) -> Job:
        """
        Crée un nouveau job.

        Raises:
            RuntimeError: Si max_jobs atteint
        """
        if len(self._jobs) >= self.max_jobs:
            raise RuntimeError(
                f"Maximum jobs reached ({self.max_jobs}). "
                "Wait for existing jobs to complete or retry later."
            )

        job = Job(
            job_id=self.generate_job_id(),
            expert=expert,
            task=task,
            mode=mode,
            context=context,
            files=files or [],
            metadata=metadata or {}
        )

        self._jobs[job.job_id] = job
        self._events[job.job_id] = asyncio.Event()
        self.logger.info(f"Job created: {job.job_id} (expert={expert}, total_jobs={len(self._jobs)})")
        return job

    async def get_job(self, job_id: str) -> Optional[Job]:
        """Récupère un job par ID. Retourne None si non trouvé."""
        return self._jobs.get(job_id)

    async def wait_for_completion(self, job_id: str, timeout: float = 55) -> Optional[Job]:
        """Wait until job reaches a terminal state. Returns job or None on timeout."""
        event = self._events.get(job_id)
        if not event:
            return self._jobs.get(job_id)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self._jobs.get(job_id)

    async def update_job(
        self,
        job_id: str,
        status: JobStatus,
        result: str = None,
        error: str = None
    ) -> None:
        """Met à jour le statut d'un job."""
        job = self._jobs.get(job_id)
        if not job:
            self.logger.warning(f"Job not found for update: {job_id}")
            return

        job.status = status

        if status == JobStatus.PROCESSING:
            job.started_at = datetime.now(timezone.utc)
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT):
            job.completed_at = datetime.now(timezone.utc)

        if result is not None:
            job.result = result
        if error is not None:
            job.error = error

        # Signal waiters when job reaches a terminal state
        if status not in (JobStatus.PENDING, JobStatus.PROCESSING):
            event = self._events.get(job_id)
            if event:
                event.set()

        self.logger.info(f"Job updated: {job_id} -> {status.value}")

    async def _cleanup_loop(self) -> None:
        """Boucle de cleanup (toutes les 5 min)."""
        while self._running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                await self._cleanup_old_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cleanup error: {e}")

    async def _cleanup_old_jobs(self) -> None:
        """Supprime jobs > 24h, marque jobs > 300s en TIMEOUT."""
        now = datetime.now(timezone.utc)
        retention_cutoff = now - timedelta(hours=self.retention_hours)
        timeout_cutoff = now - timedelta(seconds=self.job_timeout)

        jobs_to_remove = []
        jobs_to_timeout = []

        for job_id, job in self._jobs.items():
            # Remove jobs older than retention period
            if job.created_at < retention_cutoff:
                jobs_to_remove.append(job_id)
            # Mark stuck jobs as timeout
            elif job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
                ref_time = (
                    job.started_at if job.status == JobStatus.PROCESSING and job.started_at
                    else job.created_at
                )
                if ref_time < timeout_cutoff:
                    jobs_to_timeout.append(job_id)

        for job_id in jobs_to_remove:
            del self._jobs[job_id]
            self._events.pop(job_id, None)
            self.logger.info(f"Job removed (expired): {job_id}")

        for job_id in jobs_to_timeout:
            job = self._jobs[job_id]
            job.status = JobStatus.TIMEOUT
            job.completed_at = now
            job.error = f"Job timed out after {self.job_timeout}s"
            self.logger.warning(f"Job timed out: {job_id}")

        if jobs_to_remove or jobs_to_timeout:
            self.logger.info(
                f"Cleanup complete: removed={len(jobs_to_remove)}, "
                f"timed_out={len(jobs_to_timeout)}, remaining={len(self._jobs)}"
            )

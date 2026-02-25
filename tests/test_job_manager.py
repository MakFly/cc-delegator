"""Tests for job_manager.py — JobStatus, Job, JobManager."""

import asyncio
from datetime import datetime, timedelta

import pytest

from job_manager import JobStatus, Job, JobManager


# ============================================================================
# JobStatus
# ============================================================================


class TestJobStatus:

    def test_has_five_statuses(self):
        assert len(JobStatus) == 5

    def test_status_values(self):
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.PROCESSING.value == "processing"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.TIMEOUT.value == "timeout"

    def test_status_is_string_enum(self):
        assert isinstance(JobStatus.PENDING, str)
        assert JobStatus.PENDING == "pending"


# ============================================================================
# Job
# ============================================================================


class TestJob:

    def test_job_creation(self):
        job = Job(
            job_id="job_abc123",
            expert="architect",
            task="Design a system",
            mode="advisory",
            context="Some context"
        )

        assert job.job_id == "job_abc123"
        assert job.expert == "architect"
        assert job.status == JobStatus.PENDING
        assert job.result is None
        assert job.error is None

    def test_job_to_dict(self):
        job = Job(
            job_id="job_xyz789",
            expert="code_reviewer",
            task="Review this code",
            mode="implementation",
            context="Context here",
            files=["file1.ts", "file2.ts"],
            status=JobStatus.COMPLETED,
            result="Code looks good"
        )

        d = job.to_dict()

        assert d["job_id"] == "job_xyz789"
        assert d["expert"] == "code_reviewer"
        assert d["mode"] == "implementation"
        assert d["status"] == "completed"
        assert d["result"] == "Code looks good"
        assert "age_seconds" in d

    def test_job_to_dict_truncates_long_task(self):
        long_task = "x" * 200
        job = Job(
            job_id="job_long",
            expert="architect",
            task=long_task,
            mode="advisory",
            context=""
        )

        d = job.to_dict()

        assert len(d["task"]) == 103  # 100 chars + "..."
        assert d["task"].endswith("...")

    def test_job_age_seconds(self):
        job = Job(
            job_id="job_age",
            expert="architect",
            task="Task",
            mode="advisory",
            context=""
        )

        # Should be very recent
        age = job._age_seconds()
        assert age >= 0
        assert age < 1  # Less than 1 second old


# ============================================================================
# JobManager
# ============================================================================


class TestJobManager:

    def test_init_defaults(self):
        manager = JobManager()

        assert manager.job_timeout == 300
        assert manager.max_jobs == 100
        assert manager.retention_hours == 24

    def test_init_custom(self):
        manager = JobManager(
            job_timeout=600,
            max_jobs=50,
            retention_hours=12
        )

        assert manager.job_timeout == 600
        assert manager.max_jobs == 50
        assert manager.retention_hours == 12

    def test_generate_job_id(self):
        manager = JobManager()

        job_id = manager.generate_job_id()

        assert job_id.startswith("job_")
        assert len(job_id) == 16  # "job_" + 12 hex chars

    def test_generate_unique_job_ids(self):
        manager = JobManager()

        ids = [manager.generate_job_id() for _ in range(100)]

        # All IDs should be unique
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_create_job(self):
        manager = JobManager()

        job = await manager.create_job(
            expert="architect",
            task="Design system",
            mode="advisory",
            context="Context here",
            files=["file1.ts"]
        )

        assert job.job_id.startswith("job_")
        assert job.expert == "architect"
        assert job.task == "Design system"
        assert job.mode == "advisory"
        assert job.context == "Context here"
        assert job.files == ["file1.ts"]
        assert job.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_job_max_limit(self):
        manager = JobManager(max_jobs=2)

        # Create max jobs
        await manager.create_job("architect", "t1", "advisory", "", [])
        await manager.create_job("architect", "t2", "advisory", "", [])

        # Should raise when exceeding limit
        with pytest.raises(RuntimeError, match="Maximum jobs reached"):
            await manager.create_job("architect", "t3", "advisory", "", [])

    @pytest.mark.asyncio
    async def test_get_job(self):
        manager = JobManager()

        created = await manager.create_job(
            expert="architect",
            task="Task",
            mode="advisory",
            context="",
            files=[]
        )

        retrieved = await manager.get_job(created.job_id)

        assert retrieved is not None
        assert retrieved.job_id == created.job_id

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        manager = JobManager()

        job = await manager.get_job("nonexistent")

        assert job is None

    @pytest.mark.asyncio
    async def test_update_job_status(self):
        manager = JobManager()

        job = await manager.create_job(
            expert="architect",
            task="Task",
            mode="advisory",
            context="",
            files=[]
        )

        await manager.update_job(job.job_id, JobStatus.PROCESSING)

        updated = await manager.get_job(job.job_id)
        assert updated.status == JobStatus.PROCESSING
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_update_job_completed(self):
        manager = JobManager()

        job = await manager.create_job(
            expert="architect",
            task="Task",
            mode="advisory",
            context="",
            files=[]
        )

        await manager.update_job(
            job.job_id,
            JobStatus.COMPLETED,
            result="Expert response here"
        )

        updated = await manager.get_job(job.job_id)
        assert updated.status == JobStatus.COMPLETED
        assert updated.result == "Expert response here"
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_job_failed(self):
        manager = JobManager()

        job = await manager.create_job(
            expert="architect",
            task="Task",
            mode="advisory",
            context="",
            files=[]
        )

        await manager.update_job(
            job.job_id,
            JobStatus.FAILED,
            error="Something went wrong"
        )

        updated = await manager.get_job(job.job_id)
        assert updated.status == JobStatus.FAILED
        assert updated.error == "Something went wrong"

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        manager = JobManager()

        manager.start()
        assert manager._running is True
        assert manager._cleanup_task is not None

        await manager.stop()
        assert manager._running is False

    @pytest.mark.asyncio
    async def test_cleanup_old_jobs(self):
        manager = JobManager(retention_hours=1)

        # Create an old job by backdating
        old_job = await manager.create_job(
            expert="architect",
            task="Old task",
            mode="advisory",
            context="",
            files=[]
        )
        # Manually backdate the job
        manager._jobs[old_job.job_id].created_at = datetime.utcnow() - timedelta(hours=2)

        # Create a new job
        new_job = await manager.create_job(
            expert="architect",
            task="New task",
            mode="advisory",
            context="",
            files=[]
        )

        await manager._cleanup_old_jobs()

        # Old job should be removed
        assert await manager.get_job(old_job.job_id) is None
        # New job should still exist
        assert await manager.get_job(new_job.job_id) is not None

    @pytest.mark.asyncio
    async def test_cleanup_timeout_jobs(self):
        manager = JobManager(job_timeout=1)

        # Create a job and backdate it
        stuck_job = await manager.create_job(
            expert="architect",
            task="Stuck task",
            mode="advisory",
            context="",
            files=[]
        )
        # Manually backdate and set to PROCESSING
        manager._jobs[stuck_job.job_id].created_at = datetime.utcnow() - timedelta(seconds=5)
        manager._jobs[stuck_job.job_id].status = JobStatus.PROCESSING

        await manager._cleanup_old_jobs()

        # Job should be marked as TIMEOUT
        job = await manager.get_job(stuck_job.job_id)
        assert job.status == JobStatus.TIMEOUT
        assert job.error is not None

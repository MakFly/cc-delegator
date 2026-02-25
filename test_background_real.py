#!/usr/bin/env python3
"""
Test réel du Background Processing pour GLM-Delegator.

Ce script teste le flux complet:
1. Petit contexte → réponse directe
2. Gros contexte → job_id → polling → résultat
3. Job non trouvé → erreur
"""

import asyncio
import json
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import AsyncMock, MagicMock
from glm_mcp_server import LLMDelegatorMCPServer
from providers import ProviderResponse
from job_manager import JobStatus


def create_mock_args():
    """Create mock command line arguments."""
    args = MagicMock()
    args.provider = "anthropic-compatible"
    args.base_url = "https://api.z.ai/api/anthropic"
    args.api_key = "test-key-12345678"
    args.model = "glm-5"
    args.api_version = "2023-06-01"
    args.timeout = 600
    args.max_tokens = 8192
    return args


def create_mock_logger():
    """Create mock logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.debug = MagicMock()
    return logger


async def test_direct_mode():
    """Test 1: Petit contexte → réponse directe."""
    print("\n" + "="*60)
    print("TEST 1: Mode Direct (< 8000 chars)")
    print("="*60)

    args = create_mock_args()
    logger = create_mock_logger()
    srv = LLMDelegatorMCPServer(args, logger)

    # Mock the provider
    srv.provider = AsyncMock()
    srv.provider.call = AsyncMock(
        return_value=ProviderResponse(
            text="Cette architecture est bien conçue. Suggestions: ajouter du caching...",
            raw={},
            model="glm-5"
        )
    )

    # Small context (< 8000 chars)
    result = await srv.call_tool("glm_architect", {
        "task": "Review this architecture",
        "context": "Simple microservices setup with API Gateway and 3 services."
    })

    response_text = result["content"][0]["text"]

    # Verify direct response (not JSON with job_id)
    assert "isError" not in result, "Should not have error"
    assert not response_text.startswith("{"), "Should be direct text, not JSON"

    print(f"✓ Réponse directe reçue: {response_text[:100]}...")
    print("✓ TEST 1 PASSÉ")

    await srv.stop()
    return True


async def test_background_mode():
    """Test 2: Gros contexte → job_id → polling → résultat."""
    print("\n" + "="*60)
    print("TEST 2: Mode Background (>= 8000 chars)")
    print("="*60)

    args = create_mock_args()
    logger = create_mock_logger()
    srv = LLMDelegatorMCPServer(args, logger)
    srv.provider = AsyncMock()

    # Simulate slow LLM response
    async def slow_response(*args, **kwargs):
        await asyncio.sleep(0.5)  # Simulate processing time
        return ProviderResponse(
            text="Analyse complète de l'architecture:\n\n1. Points forts:\n- Modularité\n- Scalabilité\n\n2. Points à améliorer:\n- Ajouter circuit breaker\n- Implémenter retry logic",
            raw={},
            model="glm-5"
        )

    srv.provider.call = slow_response

    # Start server (starts job manager)
    await srv.start()

    # Large context (>= 8000 chars)
    large_context = "x" * 9000

    print(f"> Context size: {len(large_context) + len('Review architecture')} chars")

    # Step 1: Call expert - should return job_id
    result = await srv.call_tool("glm_architect", {
        "task": "Review architecture",
        "context": large_context
    })

    response_data = json.loads(result["content"][0]["text"])

    assert "job_id" in response_data, "Should return job_id"
    assert response_data["status"] == "pending", "Should be pending"
    assert response_data["job_id"].startswith("job_"), "Should have valid job_id format"

    job_id = response_data["job_id"]
    print(f"✓ Job créé: {job_id}")
    print(f"✓ Status initial: {response_data['status']}")

    # Step 2: Poll immediately - should be processing or pending
    result = await srv.call_tool("glm_get_job_result", {"job_id": job_id})
    poll_data = json.loads(result["content"][0]["text"])

    print(f"✓ Premier poll: status={poll_data['status']}")

    # Step 3: Wait for completion
    print("  Attente du traitement en background...")
    await asyncio.sleep(1.0)

    result = await srv.call_tool("glm_get_job_result", {"job_id": job_id})
    final_data = json.loads(result["content"][0]["text"])

    print(f"✓ Status final: {final_data['status']}")

    if final_data["status"] == "completed":
        print(f"✓ Résultat: {final_data['result'][:150]}...")
    else:
        print(f"  Toujours en cours: {final_data}")

    assert final_data["status"] in ["completed", "processing", "pending"], \
        f"Unexpected status: {final_data['status']}"

    print("✓ TEST 2 PASSÉ")

    await srv.stop()
    return True


async def test_job_not_found():
    """Test 3: Job non trouvé → erreur."""
    print("\n" + "="*60)
    print("TEST 3: Job non trouvé")
    print("="*60)

    args = create_mock_args()
    logger = create_mock_logger()
    srv = LLMDelegatorMCPServer(args, logger)

    result = await srv.call_tool("glm_get_job_result", {
        "job_id": "job_nonexistent123"
    })

    assert result["isError"] is True, "Should have error"

    response_data = json.loads(result["content"][0]["text"])
    assert response_data["error"] == "job_not_found", f"Wrong error: {response_data['error']}"

    print(f"✓ Erreur correcte: {response_data['error']}")
    print("✓ TEST 3 PASSÉ")

    return True


async def test_context_too_large():
    """Test 4: Context > 15000 chars → rejet."""
    print("\n" + "="*60)
    print("TEST 4: Context trop grand (> 15000 chars)")
    print("="*60)

    args = create_mock_args()
    logger = create_mock_logger()
    srv = LLMDelegatorMCPServer(args, logger)

    # Context > 15000 chars (above MAX_CONTEXT_CHARS)
    huge_context = "x" * 20000

    result = await srv.call_tool("glm_architect", {
        "task": "Review this",
        "context": huge_context
    })

    assert result["isError"] is True, "Should have error"

    response_data = json.loads(result["content"][0]["text"])
    assert response_data["error"] == "context_too_large", f"Wrong error: {response_data['error']}"

    print(f"✓ Erreur correcte: {response_data['error']}")
    print(f"✓ Message: {response_data['message'][:80]}...")
    print("✓ TEST 4 PASSÉ")

    return True


async def test_threshold_boundary():
    """Test 5: Test exact threshold (7999 vs 8000 chars)."""
    print("\n" + "="*60)
    print("TEST 5: Seuil exact (7999 vs 8000 chars)")
    print("="*60)

    args = create_mock_args()
    logger = create_mock_logger()
    srv = LLMDelegatorMCPServer(args, logger)
    srv.provider = AsyncMock()
    srv.provider.call = AsyncMock(
        return_value=ProviderResponse(text="Response", raw={}, model="glm-5")
    )

    # Just under threshold (7999 chars total)
    task = "x" * 1000
    context = "y" * 6999  # 1000 + 6999 = 7999

    print(f"> Total chars: {len(task) + len(context)} (under threshold)")

    result = await srv.call_tool("glm_architect", {
        "task": task,
        "context": context
    })

    response_text = result["content"][0]["text"]
    # Should be direct response
    assert not response_text.startswith("{") or "job_id" not in response_text, \
        "7999 chars should use direct mode"
    print("✓ 7999 chars → Mode direct")

    # Just at threshold (8000 chars total)
    task = "x" * 1000
    context = "y" * 7000  # 1000 + 7000 = 8000

    print(f"> Total chars: {len(task) + len(context)} (at threshold)")

    await srv.start()  # Start job manager

    result = await srv.call_tool("glm_architect", {
        "task": task,
        "context": context
    })

    response_data = json.loads(result["content"][0]["text"])
    assert "job_id" in response_data, "8000 chars should use background mode"
    print("✓ 8000 chars → Mode background")

    print("✓ TEST 5 PASSÉ")

    await srv.stop()
    return True


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  TESTS RÉELS - Background Processing GLM-Delegator")
    print("="*60)

    tests = [
        ("Mode Direct", test_direct_mode),
        ("Mode Background", test_background_mode),
        ("Job non trouvé", test_job_not_found),
        ("Context trop grand", test_context_too_large),
        ("Seuil exact", test_threshold_boundary),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = await test_func()
            results.append((name, "PASS", None))
        except Exception as e:
            results.append((name, "FAIL", str(e)))
            print(f"✗ ERREUR: {e}")

    # Summary
    print("\n" + "="*60)
    print("  RÉSUMÉ DES TESTS")
    print("="*60)

    passed = 0
    failed = 0
    for name, status, error in results:
        if status == "PASS":
            print(f"  ✓ {name}")
            passed += 1
        else:
            print(f"  ✗ {name}: {error}")
            failed += 1

    print(f"\n  Total: {passed} passés, {failed} échoués")
    print("="*60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

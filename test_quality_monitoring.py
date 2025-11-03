#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quality Monitoring Test Script
Verify that all components are properly installed and working
"""

import sys
import logging
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_imports():
    """Test that all required modules can be imported"""
    print("=" * 70)
    print("Testing Quality Monitoring Components")
    print("=" * 70)
    print()

    tests_passed = 0
    tests_failed = 0

    # Test 1: Core monitoring modules
    print("Test 1: Importing core monitoring modules...")
    try:
        from audio_quality_monitor import AudioQualityMonitor
        from network_diagnostics import NetworkDiagnostics
        from call_diagnostics_logger import CallDiagnosticsLogger
        from quality_monitoring import QualityMonitoringSession
        print("  [PASS] Core modules imported successfully")
        tests_passed += 1
    except ImportError as e:
        print(f"  [FAIL] Failed to import core modules: {e}")
        tests_failed += 1

    # Test 2: MOS scorer (optional)
    print("\nTest 2: Checking MOS scoring capability...")
    try:
        from mos_scorer import MOSScorer
        scorer = MOSScorer()
        if scorer.is_pesq_available():
            print("  [PASS] PESQ library available - MOS scoring enabled")
            tests_passed += 1
        else:
            print("  [WARN] PESQ library not available - MOS scoring disabled")
            print("     This is optional. See SETUP_GUIDE.md for installation.")
            tests_passed += 1
    except Exception as e:
        print(f"  [FAIL] MOS scorer import failed: {e}")
        tests_failed += 1

    # Test 3: Audio analysis dependencies
    print("\nTest 3: Checking audio analysis dependencies...")
    try:
        import numpy as np
        print(f"  [PASS] NumPy available (version {np.__version__})")
        tests_passed += 1
    except ImportError:
        print("  [FAIL] NumPy not available")
        tests_failed += 1

    # Test 4: Basic audio quality monitor functionality
    print("\nTest 4: Testing AudioQualityMonitor...")
    try:
        from audio_quality_monitor import AudioQualityMonitor
        monitor = AudioQualityMonitor(session_id="test-session")

        # Create dummy audio data (100ms @ 24kHz = 2400 samples = 4800 bytes)
        import struct
        dummy_audio = struct.pack('<' + 'h' * 2400, *([100] * 2400))

        metrics = monitor.analyze_chunk(dummy_audio, source="test")
        if metrics:
            print(f"  [PASS] Audio analysis working")
            print(f"     SNR: {metrics.snr:.1f} dB")
            print(f"     Peak: {metrics.peak_level:.3f}")
            tests_passed += 1
        else:
            print("  [WARN] Audio analysis returned None")
            tests_failed += 1
    except Exception as e:
        print(f"  [FAIL] AudioQualityMonitor test failed: {e}")
        tests_failed += 1

    # Test 5: Network diagnostics
    print("\nTest 5: Testing NetworkDiagnostics...")
    try:
        from network_diagnostics import NetworkDiagnostics
        net = NetworkDiagnostics(session_id="test-session")

        # Simulate chunk arrivals
        for i in range(10):
            net.record_chunk_arrival(4800)

        metrics = net.analyze_and_update()
        if metrics:
            print(f"  [PASS] Network diagnostics working")
            print(f"     Jitter: {metrics.jitter_avg_ms:.1f} ms")
            print(f"     Packet loss: {metrics.packet_loss_rate*100:.1f}%")
            tests_passed += 1
        else:
            print("  [WARN] Network diagnostics returned None")
            tests_failed += 1
    except Exception as e:
        print(f"  [FAIL] NetworkDiagnostics test failed: {e}")
        tests_failed += 1

    # Test 6: Call diagnostics logger
    print("\nTest 6: Testing CallDiagnosticsLogger...")
    try:
        from call_diagnostics_logger import CallDiagnosticsLogger
        logger_inst = CallDiagnosticsLogger(
            call_id="test-call",
            company_id="test-company"
        )

        logger_inst.log_call_start({"test": True})
        print("  [PASS] CallDiagnosticsLogger working")
        tests_passed += 1
    except Exception as e:
        print(f"  [FAIL] CallDiagnosticsLogger test failed: {e}")
        tests_failed += 1

    # Test 7: QualityMonitoringSession integration
    print("\nTest 7: Testing QualityMonitoringSession integration...")
    try:
        from quality_monitoring import QualityMonitoringSession

        config = {
            'enable-audio-quality-monitoring': True,
            'enable-network-diagnostics': True,
            'enable-mos-scoring': False,
            'enable-structured-diagnostics-logging': True,
            'quality-jitter-warning-ms': 30.0,
            'quality-packet-loss-warning': 0.10,
            'quality-rtt-warning-ms': 500.0
        }

        session = QualityMonitoringSession(
            call_id="test-call",
            company_id="test-company",
            config=config
        )

        print("  [PASS] QualityMonitoringSession initialized")
        print(f"     Audio monitoring: {session.enabled}")
        print(f"     Network diagnostics: {session.network_enabled}")
        tests_passed += 1
    except Exception as e:
        print(f"  [FAIL] QualityMonitoringSession test failed: {e}")
        tests_failed += 1

    # Summary
    print()
    print("=" * 70)
    print("Test Results Summary")
    print("=" * 70)
    print(f"  Passed: {tests_passed}")
    print(f"  Failed: {tests_failed}")
    print()

    if tests_failed == 0:
        print("SUCCESS: All tests passed! Quality monitoring is ready to use.")
        print()
        print("Next steps:")
        print("  1. Deploy your application")
        print("  2. Make a test call")
        print("  3. Check logs for quality monitoring output")
        print()
        return 0
    else:
        print("WARNING: Some tests failed. Please review errors above.")
        print()
        print("Common issues:")
        print("  - Missing dependencies: pip install -r requirements.txt")
        print("  - PESQ not installed: Optional, see SETUP_GUIDE.md")
        print()
        return 1

if __name__ == "__main__":
    exit_code = test_imports()
    sys.exit(exit_code)

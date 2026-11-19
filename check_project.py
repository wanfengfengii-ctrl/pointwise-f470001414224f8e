"""Run this project's full unittest suite and the V1 reference checks."""
import sys
import unittest


def run_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return 0 if successful else 1


def run_reference_checks():
    from withdrawal_cases import check_reference, check_withdrawal_wire

    try:
        check_reference()
        check_withdrawal_wire()
    except BaseException as exc:  # propagate the project's own failure style
        print(f'REFERENCE SUMMARY result=FAIL error={type(exc).__name__}: {exc}')
        return 1
    print('REFERENCE SUMMARY result=PASS')
    return 0


def main():
    return run_suite() | run_reference_checks()


if __name__ == '__main__':
    raise SystemExit(main())

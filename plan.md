1. **Add test cases for `get_forwarded_proto` in `tests/test_server.py`.**
   - Insert a new `GetForwardedProtoTests` class subclassing `unittest.TestCase` into `tests/test_server.py`, right before `if __name__ == '__main__': unittest.main()`.
   - Setup a `DummyHandler` that bypasses socket initialization, as instructed in memory.
   - Create tests to verify X-Forwarded-Proto single and multiple values.
   - Create tests for invalid values in X-Forwarded-Proto falling back to 'http' (if Host is provided) or ''.
   - Create tests for fallback headers: X-Forwarded-Scheme and X-Url-Scheme.
   - Create tests for Front-End-Https and X-Forwarded-Ssl falling back to 'https' when truthy ('on', '1', 'true', case-insensitive).
   - Create tests for non-truthy values of Front-End-Https.
   - Create tests for defaults when no proxy headers exist but 'Host' is present ('http'), and when no headers exist ('').

2. **Run the test suite to verify the changes.**
   - Use `python3 -m unittest discover -s tests` to ensure all tests pass.
   - Remove any temporary scratch files (e.g., `dummy_test.py`).

3. **Complete pre-commit steps.**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

4. **Submit the PR.**
   - Submit the PR with appropriate commit title and description indicating added test coverage for `get_forwarded_proto`.

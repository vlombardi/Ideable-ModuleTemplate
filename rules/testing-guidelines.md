---
trigger: on-demand
---

> Load this file during the **test** step (step 7) of the development process.

## Testing

### Test Organization

* **Test Locations**: Tests are organized in `TESTS/` directories at both module and sub-module levels:
  - **Module-level tests**: `modules/<MODULE>/TESTS/` - integration tests across sub-modules
  - **Sub-module-level tests**: `modules/<MODULE>/<SUB_MODULE>/TESTS/` - unit and component tests

### Test Types

Each test suite should include appropriate test types based on the sub-module:

* **Unit Tests**: Test individual functions, classes, and components in isolation
  - Must have high coverage of critical business logic
  - Should be fast and independent
  - Mock external dependencies

* **Integration Tests**: Test interactions between components within a sub-module
  - Database interactions
  - API endpoint functionality
  - Service-to-service communication

* **End-to-End Tests**: Test complete user workflows across sub-modules
  - Critical user journeys
  - Multi-sub-module interactions
  - Real-world scenarios

### Test Execution

* **Test Step**: Tests are executed during the **test** step of the development process (step 7)
* **Test Frameworks**: Use standard frameworks appropriate for each technology:
  - **Python**: `pytest`, `unittest`
  - **JavaScript/TypeScript**: `jest`, `vitest`, `cypress` (for E2E)

### Test Reports

* **Report Generation**: After running tests, generate a comprehensive report:
  - **Location**: `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md` at the project root
  - **Contents**:
    - Test execution summary (passed/failed/skipped)
    - Code coverage metrics
    - Failed test details with error messages
    - Recommendations for improvements

### Test Best Practices

1. **Isolation**: Tests must be independent and not rely on execution order
2. **Clarity**: Test names should clearly describe what is being tested
3. **Maintainability**: Update tests whenever related code changes
4. **Documentation**: Document complex test scenarios and edge cases
5. **Coverage**: Aim for high coverage of critical paths, but prioritize meaningful tests over coverage percentages
6. **Speed**: Keep unit tests fast; reserve longer-running tests for integration suites

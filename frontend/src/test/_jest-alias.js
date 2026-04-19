// Alias vitest's `vi` as `jest` so @testing-library/dom's fake-timer detection works.
// @testing-library/dom's waitFor detects fake timers via `typeof jest !== 'undefined'`.
// Under vitest, `vi` exists instead of `jest`, so waitFor falls back to its
// real-timer path AND @testing-library/react's asyncWrapper drains via
// `setTimeout(0)`, which IS faked by vi.useFakeTimers() → causes indefinite
// hangs in tests that combine fake timers with waitFor. Aliasing jest → vi
// lets testing-library take the fake-timer path which advances timers via
// jest.advanceTimersByTime.
import { vi } from 'vitest'

if (typeof globalThis.jest === 'undefined') {
  globalThis.jest = vi
}

from __future__ import division, print_function, absolute_import

import numpy as np
import vip_hci as vip
import pytest


def aarc(actual, desired, rtol=1e-5, atol=1e-6):
    """
    Assert array-compare. Like ``np.allclose``, but with different defaults.

    Notes
    -----
    Default values for
    - ``np.allclose``: ``atol=1e-8, rtol=1e-5``
    - ``np.testing.assert_allclose``: ``atol=0, rtol=1e-7``

    IDL's `FLOAT` is 32bit (precision of ~1e-6 to ~1e-7), while python uses
    64-bit floats internally. To pass the comparison, `atol` has to be chosen
    accordingly. The contribution of `rtol` is dominant for large numbers, where
    an absolute comparison to `1e-6` would not make sense.

    """
    __tracebackhide__ = True  # Hide traceback for pytest
    np.testing.assert_allclose(actual, desired, rtol=rtol, atol=atol)

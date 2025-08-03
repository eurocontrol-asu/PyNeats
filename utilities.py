import numpy as np

def is_nan_string(s):
    try:
        return np.isnan(float(s))
    except ValueError:
        return False  # If the string cannot be converted to float, it's not NaN.
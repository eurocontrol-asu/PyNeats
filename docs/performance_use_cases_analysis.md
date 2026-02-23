# Performance Use Cases: Current Implementation vs. Specification

Hi Dennis,

I went through your use case list and compared it against the current `bada_model.py` implementation. Below is what I found.

## Notation
- **AM** = Aircraft Mass
- **FF** = Fuel Flow  
- **EE** = Engine Efficiency
- **TAS** = True Airspeed
- **--** = Not provided

## Current Implementation Logic

The performance model currently works as follows:

1. **TAS** is always recomputed from ground speed + wind (airline-provided values are overwritten)
2. If both FF and EE are provided, we skip BADA entirely (early exit)
3. AM is used from input if available; otherwise estimated iteratively via BADA
4. FF is preserved if provided; otherwise computed from BADA
5. EE is preserved if provided; otherwise computed from thrust/TAS/FF

Note: There is no "AM from FF" calculation. When AM is missing, we use iterative BADA estimation.

## Case-by-Case Comparison

| Case | Provided | Your Specification | Match? | Notes |
|------|----------|-------------------|--------|-------|
| 1 | AM, FF, EE, TAS | Use all from airline | No | TAS overwritten |
| 2 | FF, EE, TAS | AM from FF | No | TAS overwritten; no AM-from-FF logic |
| 3 | AM, EE, TAS | FF from AM | No | TAS overwritten |
| 4 | AM, FF, TAS | EE from AM+trajectory | No | TAS overwritten |
| 5 | AM, FF, EE | TAS from GS+wind | **Yes** | |
| 6 | EE, TAS | Sim: AM,FF from model | No | TAS overwritten |
| 7 | FF, TAS | AM from FF; EE from trajectory | No | TAS overwritten; AM via iteration not FF |
| 8 | FF, EE | AM from FF; TAS from GS+wind | No | Early exit prevents AM calculation |
| 9 | AM, TAS | FF,EE from model | No | TAS overwritten |
| 10 | AM, EE | FF from AM; TAS from GS+wind | **Yes** | |
| 11 | AM, FF | TAS from GS+wind; EE from trajectory | **Yes** | |
| 12 | TAS | Sim: AM,FF,EE from model | No | TAS overwritten |
| 13 | EE | Sim: AM,FF,TAS from model | **Yes** | |
| 14 | FF | Sim: AM,EE,TAS from model | **Yes** | |
| 15 | AM | Sim: FF,EE,TAS from model | **Yes** | |
| 16 | (none) | Sim: all from model | **Yes** | |

**Result: 7/16 match, 9/16 differ**

## Main Discrepancies

### 1. TAS always overwritten (affects 8 cases)

In `_compute_ground_and_true_airspeed()`, we unconditionally compute TAS from ground speed and wind. If the airline provides TAS, it gets replaced.

This is straightforward to fix—just check if the column exists before computing.

### 2. No "AM from FF" logic (affects cases 2, 7, 8)

Your spec mentions deriving AM from FF in several cases. Currently we don't have this. When AM is missing, we run iterative BADA estimation instead.

Question: Is the iterative approach acceptable, or do you specifically need AM derived from FF? The iterative method is arguably more physically consistent since it uses the full performance model.

### 3. Early exit skips AM calculation (case 8)

When FF and EE are both provided, we skip BADA entirely. This means AM never gets computed in case 8.

We could either remove the early exit or add AM calculation before exiting.

## Next Steps

Let me know how you'd like to proceed:
1. Fix TAS handling (preserve airline values when provided)
2. Clarify the AM-from-FF requirement
3. Address case 8 early exit behavior

Best,

#!/usr/bin/env python3
import itertools
import json
import os
import subprocess
import sys
from collections import Counter

from sympy import Poly, symbols

PR = 2305843009213693951  # 2^61 - 1


def mod(x: int) -> int:
    return x % PR


def inv(x: int) -> int:
    x %= PR
    if x == 0:
        raise ZeroDivisionError("inv(0)")
    return pow(x, PR - 2, PR)


def run_probe(x: int) -> dict:
    env = os.environ.copy()
    env["SLOWGOLD_X"] = str(x)
    # Probe prints "connected" then one JSON line. Network/service can be flaky,
    # so retry a few times and extract the last JSON-looking line.
    for _ in range(6):
        try:
            out = subprocess.check_output(
                ["bash", "-lc", "timeout 420s dist/emp-zk/bin/test_arith_slowgold_probe"],
                env=env,
                text=True,
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as e:
            out = e.output or ""
        lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("{")]
        if lines:
            return json.loads(lines[-1])
    raise RuntimeError(f"probe failed for X={x}")


def a1_from_row(r: dict) -> int:
    seed = r["seed"] % PR
    if seed == 0:
        raise ZeroDivisionError("seed=0")
    # V = seed * A1 for the last multiplication gate (due to a bug in the check loop).
    return (r["V"] % PR) * inv(seed) % PR


def solve_linear_system_3(rows: list[dict]) -> tuple[int, int, int]:
    # kb*a + ka*b + delta*p = A1 + kc
    M = []
    rhs = []
    for r in rows:
        A1 = a1_from_row(r)
        M.append([r["kb"] % PR, r["ka"] % PR, r["delta"] % PR])
        rhs.append((A1 + (r["kc"] % PR)) % PR)

    # Gaussian elimination for 3x3.
    M = [row[:] for row in M]
    rhs = rhs[:]
    n = 3
    for col in range(n):
        piv = None
        for i in range(col, n):
            if M[i][col] % PR != 0:
                piv = i
                break
        if piv is None:
            raise ValueError("singular")
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
            rhs[col], rhs[piv] = rhs[piv], rhs[col]
        invp = inv(M[col][col])
        for j in range(col, n):
            M[col][j] = (M[col][j] * invp) % PR
        rhs[col] = (rhs[col] * invp) % PR
        for i in range(n):
            if i == col:
                continue
            factor = M[i][col] % PR
            if factor == 0:
                continue
            for j in range(col, n):
                M[i][j] = (M[i][j] - factor * M[col][j]) % PR
            rhs[i] = (rhs[i] - factor * rhs[col]) % PR

    a, b, p = rhs
    if (a * b) % PR != p:
        raise ValueError("inconsistent: p != a*b")
    return a, b, p


def solve_a_b_for_X(x: int, max_tries: int = 8) -> tuple[int, int]:
    rows = []
    for _ in range(max_tries):
        r = run_probe(x)
        # Drop degenerate seeds early.
        if (r["seed"] % PR) == 0:
            continue
        rows.append(r)
        if len(rows) < 3:
            continue
        # Try all 3-subsets until one inverts.
        for comb in itertools.combinations(rows, 3):
            try:
                a, b, _p = solve_linear_system_3(list(comb))
                return a, b
            except Exception:
                pass
    raise RuntimeError(f"failed to solve for X={x} after {max_tries} probes")


def poly_add(a: list[int], b: list[int]) -> list[int]:
    n = max(len(a), len(b))
    out = [0] * n
    for i in range(n):
        out[i] = ( (a[i] if i < len(a) else 0) + (b[i] if i < len(b) else 0) ) % PR
    # trim
    while len(out) > 1 and out[-1] == 0:
        out.pop()
    return out


def poly_mul(a: list[int], b: list[int]) -> list[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        if ai == 0:
            continue
        for j, bj in enumerate(b):
            out[i + j] = (out[i + j] + ai * bj) % PR
    while len(out) > 1 and out[-1] == 0:
        out.pop()
    return out


def lagrange_interpolate(xs: list[int], ys: list[int]) -> list[int]:
    # Returns coeffs c0..c_{n-1} for degree <= n-1 polynomial with f(xs[i])=ys[i].
    n = len(xs)
    assert n == len(ys)
    coeffs = [0]
    for i in range(n):
        xi = xs[i] % PR
        yi = ys[i] % PR
        # basis numerator: prod_{j!=i} (x - xj)
        num = [1]  # poly = 1
        den = 1
        for j in range(n):
            if i == j:
                continue
            xj = xs[j] % PR
            num = poly_mul(num, [(-xj) % PR, 1])  # (x - xj)
            den = (den * ((xi - xj) % PR)) % PR
        scale = (yi * inv(den)) % PR
        term = [(c * scale) % PR for c in num]
        coeffs = poly_add(coeffs, term)
    # pad to n
    coeffs += [0] * (n - len(coeffs))
    return [c % PR for c in coeffs[:n]]


def roots_from_poly(coeffs: list[int]) -> list[int]:
    x = symbols("x")
    expr = 0
    for i, c in enumerate(coeffs):
        expr = (expr + int(c) * (x ** i))
    P = Poly(expr, x, modulus=PR)
    lc = int(P.LC()) % PR
    if lc != 1:
        P = Poly(P * inv(lc), x, modulus=PR)

    factors = P.factor_list()[1]
    roots = []
    for f, e in factors:
        if f.degree() != 1:
            raise RuntimeError(f"unexpected non-linear factor: deg={f.degree()}")
        a1, a0 = [int(c) % PR for c in f.all_coeffs()]  # a1*x + a0
        r = (-a0 * inv(a1)) % PR
        roots.extend([r] * e)
    if len(roots) != 9:
        raise RuntimeError(f"expected 9 roots, got {len(roots)}")
    return roots


def submit(values: list[int]) -> str:
    env = os.environ.copy()
    env["SLOWGOLD_GUESSES"] = ",".join(str(int(v)) for v in values)
    env["SLOWGOLD_X"] = "0"
    out = subprocess.check_output(
        ["bash", "-lc", "timeout 240s dist/emp-zk/bin/test_arith_slowgold_submit"],
        env=env,
        text=True,
        stderr=subprocess.STDOUT,
    )
    return out


def main() -> int:
    # 10 points to interpolate a degree-9 polynomial a(X) = prod_{j=0..8} (v_j + X).
    xs = list(range(10))
    ays = []
    v9_votes = []

    for x in xs:
        a, b = solve_a_b_for_X(x)
        ays.append(a)
        v9_votes.append((b - x) % PR)
        print(f"[X={x}] a={a} b={b} v9={v9_votes[-1]}", file=sys.stderr, flush=True)

    v9 = Counter(v9_votes).most_common(1)[0][0]
    print(f"[v9] {v9}", file=sys.stderr, flush=True)

    coeffs = lagrange_interpolate(xs, ays)  # c0..c9
    roots = roots_from_poly(coeffs)  # roots are X = -v_j
    v_list = [(-r) % PR for r in roots]
    if v9 in v_list:
        # Rare, but handle duplicates gracefully.
        pass
    v_list.append(v9)

    # Sanity: 10 values.
    if len(v_list) != 10:
        raise RuntimeError("expected 10 values")

    # Submit. Any order is fine (server checks permutation).
    out = submit(v_list)
    sys.stdout.write(out)
    if "lactf{" in out:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

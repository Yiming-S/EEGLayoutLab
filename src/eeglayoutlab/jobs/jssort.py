"""V8's ``Array.prototype.sort(comparefn)`` (third_party/v8/builtins/array-sort.tq), statement by statement.

V8 sorts with TimSort: natural runs extended to a minimum run length by binary insertion, merged with galloping
under V8's merge-collapse rule (CPython's ``list.sort`` merges in another order since 3.11). V8 14 (Node 26) first
sorts an array of up to ``INSERTION_LIMIT`` items by binary insertion alone; older V8 has no such path (Node 24's
V8 13.6 measured, Node 22's 12.4 older still), which ``insertion_limit=2`` reproduces. The port calls the
comparator with the same arguments in the same order as that V8 does, so a comparator that answers as Node's does
and throws for some pairs (Node's ``(b.finished_at || '').localeCompare(...)`` on a record whose ``finished_at`` is
not a string) throws exactly when V8's sort does, and an inconsistent comparator leaves the same order. The array
holds no ``undefined`` and no holes (V8 moves those out before sorting).

The service follows Node 26: an array of 3 to 7 items whose comparator throws for some pairs can sort on one side
and fail on the other under Node 22 or 24. ``tests/service/test_library_messages.py`` measures the limit on the
Node it runs and compares every comparison with V8's; the parity tests set ``INSERTION_LIMIT`` to it.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

__all__ = ['INSERTION_LIMIT', 'array_sort']

_MIN_GALLOP_WINS = 7
INSERTION_LIMIT = 7  # Node 26 (V8 14.6), measured


def array_sort(items: list, compare: Callable[[Any, Any], Any], *, insertion_limit: Optional[int] = None) -> list:
    """``items.sort(compare)``: a sorted copy; ``compare``'s exceptions propagate, as V8's sort rethrows them.
    ``insertion_limit`` is the longest array V8 sorts by binary insertion alone (by default ``INSERTION_LIMIT``)."""
    work = list(items)
    if len(work) >= 2:
        _TimSort(work, compare, INSERTION_LIMIT if insertion_limit is None else insertion_limit).sort()
    return work


class _TimSort:
    def __init__(self, work: list, compare: Callable[[Any, Any], Any], insertion_limit: int):
        self.work = work
        self.user = compare
        self.insertion_limit = insertion_limit
        self.min_gallop = _MIN_GALLOP_WINS
        self.runs: list[list[int]] = []  # [base, length] pending runs

    def compare(self, x: Any, y: Any) -> float:
        """``SortCompareUserFn``: the comparator's number, ``NaN`` as 0."""
        order = self.user(x, y)
        return 0 if isinstance(order, float) and math.isnan(order) else order

    # ArrayTimSortImpl
    def sort(self) -> None:
        remaining = len(self.work)
        if remaining <= self.insertion_limit:
            self.binary_insertion_sort(0, 0, remaining)
            return
        low = 0
        min_run = _min_run_length(remaining)
        while remaining:
            run = self.count_and_make_run(low, low + remaining)
            if run < min_run:
                forced = min(min_run, remaining)
                self.binary_insertion_sort(low, low + run, low + forced)
                run = forced
            self.runs.append([low, run])
            self.merge_collapse()
            low += run
            remaining -= run
        self.merge_force_collapse()

    def count_and_make_run(self, low_arg: int, high: int) -> int:
        work = self.work
        low = low_arg + 1
        if low == high:
            return 1
        run = 2
        descending = self.compare(work[low], work[low - 1]) < 0
        previous = work[low]
        for index in range(low + 1, high):
            current = work[index]
            order = self.compare(current, previous)
            if (order >= 0) if descending else (order < 0):
                break
            previous = current
            run += 1
        if descending:
            work[low_arg:low_arg + run] = work[low_arg:low_arg + run][::-1]
        return run

    def binary_insertion_sort(self, low: int, start: int, high: int) -> None:
        work = self.work
        if low == start:
            start += 1
        for start in range(start, high):
            left, right = low, start
            pivot = work[right]
            while left < right:
                middle = left + ((right - left) >> 1)
                if self.compare(pivot, work[middle]) < 0:
                    right = middle
                else:
                    left = middle + 1
            work[left + 1:start + 1] = work[left:start]
            work[left] = pivot

    def _invariant(self, n: int) -> bool:
        """``RunInvariantEstablished``: ``length(n - 2) > length(n - 1) + length(n)``."""
        if n < 2:
            return True
        runs = self.runs
        return runs[n - 2][1] > runs[n - 1][1] + runs[n][1]

    def merge_collapse(self) -> None:
        runs = self.runs
        while len(runs) > 1:
            n = len(runs) - 2
            if not self._invariant(n + 1) or not self._invariant(n):
                if runs[n - 1][1] < runs[n + 1][1]:
                    n -= 1
                self.merge_at(n)
            elif runs[n][1] <= runs[n + 1][1]:
                self.merge_at(n)
            else:
                break

    def merge_force_collapse(self) -> None:
        runs = self.runs
        while len(runs) > 1:
            n = len(runs) - 2
            if n > 0 and runs[n - 1][1] < runs[n + 1][1]:
                n -= 1
            self.merge_at(n)

    def merge_at(self, i: int) -> None:
        work, runs = self.work, self.runs
        base_a, length_a = runs[i]
        base_b, length_b = runs[i + 1]
        runs[i][1] = length_a + length_b
        del runs[i + 1]
        k = self.gallop_right(work, work[base_b], base_a, length_a, 0)
        base_a += k
        length_a -= k
        if length_a == 0:
            return
        length_b = self.gallop_left(work, work[base_a + length_a - 1], base_b, length_b, length_b - 1)
        if length_b == 0:
            return
        if length_a <= length_b:
            self.merge_low(base_a, length_a, base_b, length_b)
        else:
            self.merge_high(base_a, length_a, base_b, length_b)

    def gallop_left(self, array: list, key: Any, base: int, length: int, hint: int) -> int:
        last, offset = 0, 1
        if self.compare(array[base + hint], key) < 0:
            limit = length - hint
            while offset < limit:
                if self.compare(array[base + hint + offset], key) >= 0:
                    break
                last, offset = offset, (offset << 1) + 1
            offset = min(offset, limit)
            last, offset = last + hint, offset + hint
        else:
            limit = hint + 1
            while offset < limit:
                if self.compare(array[base + hint - offset], key) < 0:
                    break
                last, offset = offset, (offset << 1) + 1
            offset = min(offset, limit)
            last, offset = hint - offset, hint - last
        last += 1
        while last < offset:
            middle = last + ((offset - last) >> 1)
            if self.compare(array[base + middle], key) < 0:
                last = middle + 1
            else:
                offset = middle
        return offset

    def gallop_right(self, array: list, key: Any, base: int, length: int, hint: int) -> int:
        last, offset = 0, 1
        if self.compare(key, array[base + hint]) < 0:
            limit = hint + 1
            while offset < limit:
                if self.compare(key, array[base + hint - offset]) >= 0:
                    break
                last, offset = offset, (offset << 1) + 1
            offset = min(offset, limit)
            last, offset = hint - offset, hint - last
        else:
            limit = length - hint
            while offset < limit:
                if self.compare(key, array[base + hint + offset]) < 0:
                    break
                last, offset = offset, (offset << 1) + 1
            offset = min(offset, limit)
            last, offset = last + hint, offset + hint
        last += 1
        while last < offset:
            middle = last + ((offset - last) >> 1)
            if self.compare(key, array[base + middle]) < 0:
                offset = middle
            else:
                last = middle + 1
        return offset

    def merge_low(self, base_a: int, length_a: int, base_b: int, length_b: int) -> None:
        work = self.work
        temp = work[base_a:base_a + length_a]
        dest, cursor_temp, cursor_b = base_a, 0, base_b
        work[dest] = work[cursor_b]
        dest += 1
        cursor_b += 1

        def succeed() -> None:
            if length_a > 0:
                work[dest:dest + length_a] = temp[cursor_temp:cursor_temp + length_a]

        def copy_b() -> None:
            work[dest:dest + length_b] = work[cursor_b:cursor_b + length_b]
            work[dest + length_b] = temp[cursor_temp]

        length_b -= 1
        if length_b == 0:
            return succeed()
        if length_a == 1:
            return copy_b()
        min_gallop = self.min_gallop
        while True:
            wins_a = wins_b = 0
            while True:
                if self.compare(work[cursor_b], temp[cursor_temp]) < 0:
                    work[dest] = work[cursor_b]
                    dest += 1
                    cursor_b += 1
                    wins_b += 1
                    length_b -= 1
                    wins_a = 0
                    if length_b == 0:
                        return succeed()
                    if wins_b >= min_gallop:
                        break
                else:
                    work[dest] = temp[cursor_temp]
                    dest += 1
                    cursor_temp += 1
                    wins_a += 1
                    length_a -= 1
                    wins_b = 0
                    if length_a == 1:
                        return copy_b()
                    if wins_a >= min_gallop:
                        break
            min_gallop += 1
            first = True
            while wins_a >= _MIN_GALLOP_WINS or wins_b >= _MIN_GALLOP_WINS or first:
                first = False
                min_gallop = max(1, min_gallop - 1)
                self.min_gallop = min_gallop
                wins_a = self.gallop_right(temp, work[cursor_b], cursor_temp, length_a, 0)
                if wins_a > 0:
                    work[dest:dest + wins_a] = temp[cursor_temp:cursor_temp + wins_a]
                    dest += wins_a
                    cursor_temp += wins_a
                    length_a -= wins_a
                    if length_a == 1:
                        return copy_b()
                    if length_a == 0:
                        return succeed()
                work[dest] = work[cursor_b]
                dest += 1
                cursor_b += 1
                length_b -= 1
                if length_b == 0:
                    return succeed()
                wins_b = self.gallop_left(work, temp[cursor_temp], cursor_b, length_b, 0)
                if wins_b > 0:
                    work[dest:dest + wins_b] = work[cursor_b:cursor_b + wins_b]
                    dest += wins_b
                    cursor_b += wins_b
                    length_b -= wins_b
                    if length_b == 0:
                        return succeed()
                work[dest] = temp[cursor_temp]
                dest += 1
                cursor_temp += 1
                length_a -= 1
                if length_a == 1:
                    return copy_b()
            min_gallop += 1
            self.min_gallop = min_gallop

    def merge_high(self, base_a: int, length_a: int, base_b: int, length_b: int) -> None:
        work = self.work
        temp = work[base_b:base_b + length_b]
        dest, cursor_temp, cursor_a = base_b + length_b - 1, length_b - 1, base_a + length_a - 1
        work[dest] = work[cursor_a]
        dest -= 1
        cursor_a -= 1

        def succeed() -> None:
            if length_b > 0:
                start = dest - (length_b - 1)
                work[start:start + length_b] = temp[0:length_b]

        def copy_a() -> None:
            target, source = dest - length_a, cursor_a - length_a
            work[target + 1:target + 1 + length_a] = work[source + 1:source + 1 + length_a]
            work[target] = temp[cursor_temp]

        length_a -= 1
        if length_a == 0:
            return succeed()
        if length_b == 1:
            return copy_a()
        min_gallop = self.min_gallop
        while True:
            wins_a = wins_b = 0
            while True:
                if self.compare(temp[cursor_temp], work[cursor_a]) < 0:
                    work[dest] = work[cursor_a]
                    dest -= 1
                    cursor_a -= 1
                    wins_a += 1
                    length_a -= 1
                    wins_b = 0
                    if length_a == 0:
                        return succeed()
                    if wins_a >= min_gallop:
                        break
                else:
                    work[dest] = temp[cursor_temp]
                    dest -= 1
                    cursor_temp -= 1
                    wins_b += 1
                    length_b -= 1
                    wins_a = 0
                    if length_b == 1:
                        return copy_a()
                    if wins_b >= min_gallop:
                        break
            min_gallop += 1
            first = True
            while wins_a >= _MIN_GALLOP_WINS or wins_b >= _MIN_GALLOP_WINS or first:
                first = False
                min_gallop = max(1, min_gallop - 1)
                self.min_gallop = min_gallop
                k = self.gallop_right(work, temp[cursor_temp], base_a, length_a, length_a - 1)
                wins_a = length_a - k
                if wins_a > 0:
                    dest -= wins_a
                    cursor_a -= wins_a
                    work[dest + 1:dest + 1 + wins_a] = work[cursor_a + 1:cursor_a + 1 + wins_a]
                    length_a -= wins_a
                    if length_a == 0:
                        return succeed()
                work[dest] = temp[cursor_temp]
                dest -= 1
                cursor_temp -= 1
                length_b -= 1
                if length_b == 1:
                    return copy_a()
                k = self.gallop_left(temp, work[cursor_a], 0, length_b, length_b - 1)
                wins_b = length_b - k
                if wins_b > 0:
                    dest -= wins_b
                    cursor_temp -= wins_b
                    work[dest + 1:dest + 1 + wins_b] = temp[cursor_temp + 1:cursor_temp + 1 + wins_b]
                    length_b -= wins_b
                    if length_b == 1:
                        return copy_a()
                    if length_b == 0:
                        return succeed()
                work[dest] = work[cursor_a]
                dest -= 1
                cursor_a -= 1
                length_a -= 1
                if length_a == 0:
                    return succeed()
            min_gallop += 1
            self.min_gallop = min_gallop


def _min_run_length(n: int) -> int:
    """``ComputeMinRunLength``: ``n`` below 64, else between 32 and 64."""
    r = 0
    while n >= 64:
        r |= n & 1
        n >>= 1
    return n + r

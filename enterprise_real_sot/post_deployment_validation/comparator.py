"""Protocol-agnostic recursive state tree comparator."""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class FieldComparison:
    """Result of comparing a single field between desired and actual state."""

    field_path: str
    expected_value: Any
    actual_value: Any
    status: str  # "PASS" or "DRIFT"
    reason: Optional[str] = None


class StateComparator:
    """Generic, protocol-agnostic data structure comparator.

    Recursively compares normalized desired dictionary trees against normalized
    actual dictionary trees without knowing vendor, device-role, or protocol specifics.
    """

    def compare(
        self,
        desired_tree: Mapping[str, Any],
        actual_tree: Mapping[str, Any],
        path_prefix: str = "",
    ) -> List[FieldComparison]:
        """Recursively compare desired state against actual state."""
        results: List[FieldComparison] = []

        if not isinstance(desired_tree, Mapping):
            return results

        for key, expected_val in desired_tree.items():
            current_path = f"{path_prefix}.{key}" if path_prefix else str(key)
            actual_val = actual_tree.get(key) if isinstance(actual_tree, Mapping) else None

            if isinstance(expected_val, Mapping):
                # Recurse down nested dictionary hierarchy
                nested_actual = actual_val if isinstance(actual_val, Mapping) else {}
                results.extend(
                    self.compare(expected_val, nested_actual, path_prefix=current_path)
                )
            else:
                # Compare primitive field values
                status, reason = self._compare_primitive_values(expected_val, actual_val)
                results.append(
                    FieldComparison(
                        field_path=current_path,
                        expected_value=expected_val,
                        actual_value=actual_val,
                        status=status,
                        reason=reason,
                    )
                )

        return results

    @staticmethod
    def _compare_primitive_values(expected: Any, actual: Any) -> tuple[str, Optional[str]]:
        """Compare primitive expected and actual values."""
        if actual is None:
            return "DRIFT", "Missing in actual state"

        # Case-insensitive comparison for strings
        if isinstance(expected, str) and isinstance(actual, str):
            if expected.strip().lower() == actual.strip().lower():
                return "PASS", None
            return "DRIFT", "Value mismatch"

        # Direct equality check for booleans, ints, floats, lists
        if expected == actual:
            return "PASS", None

        return "DRIFT", "Value mismatch"

"""Keep sortable statistics numeric while formatting their presentation."""
from collections.abc import Sequence
from typing import Any

import pandas as pd
import streamlit as st


def render_numeric_table(rows: list[dict[str, Any]], rate_columns: Sequence[str]) -> None:
    table = pd.DataFrame(rows)
    # Explicit numeric types also preserve all-missing columns as numeric nulls.
    table = table.astype({column: "float64" for column in rate_columns})
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            column: st.column_config.NumberColumn(format="%.2f")
            for column in rate_columns
        },
    )

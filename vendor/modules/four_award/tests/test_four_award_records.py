from __future__ import annotations

from modules.four_award.models import FourAwardRecord
from modules.four_award.records import _insert_rows, parse_records_table, render_records_table


def test_records_table_uses_sql_model_to_sort_and_recalculate_ordinals():
    table = """{| class="wikitable sortable"
! User
! Article
! Award date
! Creation date
! DYK date
! GA date
! FA date
|-
| [[User:Zed|Zed]] || [[Zed article]] || {{dts|2024|01|01}} || {{dts|2020|01|01}} || {{dts|2020|01|02}} || {{dts|2020|01|03}} || {{dts|2020|01|04}}
|}
"""
    updated = _insert_rows(
        table,
        [
            FourAwardRecord(
                user="Alice",
                display_user="Alice",
                article="Alice article",
                award_date="2024-02-01",
                creation_date="2020-02-01",
                dyk_date="2020-02-02",
                ga_date="2020-02-03",
                fa_date="2020-02-04",
            ),
            FourAwardRecord(
                user="Zed",
                display_user="Zed",
                article="Second Zed article",
                award_date="2024-03-01",
                creation_date="2020-03-01",
                dyk_date="2020-03-02",
                ga_date="2020-03-03",
                fa_date="2020-03-04",
            ),
        ],
    )

    alice_index = updated.index("[[User:Alice|Alice]]")
    zed_index = updated.index("[[User:Zed|Zed]] || [[Zed article]]")
    second_zed_index = updated.index("[[User:Zed|Zed]] (2)")

    assert alice_index < zed_index < second_zed_index
    assert "{{dts|2024|02|01}}" in updated
    assert "{{dts|2024|03|01}}" in updated


def test_records_table_preserves_unparsed_rows_when_rerendering():
    table = """{| class="wikitable"
! User
! Article
|-
| colspan="7" | Manual note row
|}
"""
    model = parse_records_table(table)
    rendered = render_records_table(
        model,
        [
            FourAwardRecord(
                user="Example",
                article="Example article",
                award_date="2024-01-01",
                creation_date="2020-01-01",
                dyk_date="2020-01-02",
                ga_date="2020-01-03",
                fa_date="2020-01-04",
            )
        ],
    )

    assert '| colspan="7" | Manual note row' in rendered
    assert "[[User:Example|Example]]" in rendered
    assert rendered.endswith("|}\n")

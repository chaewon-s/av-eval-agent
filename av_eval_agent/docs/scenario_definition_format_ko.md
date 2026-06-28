# Scenario Definition Format

## Source Format

```text
과-19_시나리오_정의서_6-layer_v2
```

## Header

| Field | Example |
|---|---|
| scenario_id | `scenario_2` |
| scenario_type | `cut_in` |
| ego_vehicle | `cav_0` |
| target_vehicle | `background_vehicle_1` |
| map | `Town06` |
| v2x | `enabled` |

## Table Columns

```text
레이어 / 항목 / 요소 / 설명 / 시험 시나리오
```

## 6 Layers

| Layer | Data |
|---|---|
| 1 | road and map |
| 2 | traffic objects |
| 3 | variable infrastructure |
| 4 | scenario participants |
| 5 | environment |
| 6 | digital information |

## Output Files

| File | Content |
|---|---|
| `scenario_definition.json` | full internal definition |
| `scenario_definition_form.json` | table-only JSON |
| `scenario_definition_form.csv` | 5-column table |

## Autofill Rules

| Missing Item | Default |
|---|---|
| map | scenario default |
| ego vehicle | `cav_0` |
| target vehicle | scenario default |
| weather | clear |
| traffic density | normal |
| V2X | request value or scenario default |

## Validation

| Check | Output |
|---|---|
| missing required field | validation error |
| ambiguous value | validation warning |
| unsafe execution request | approval required |
| external simulator missing | dry-run plan |

## KPI Link

| Scenario Field | KPI Use |
|---|---|
| V2X | safety and traffic impact comparison |
| speed | control and safety KPI |
| sensor condition | perception KPI context |
| cut-in distance | TTC and required deceleration |
| traffic density | delay and flow efficiency |

# Param-Table Template

A Hugo shortcode and data-file schema that renders scenario parameter tables on the [krkn-chaos website](https://github.com/krkn-chaos/website) from data files.

It lets the docs-sync bot ([#320](https://github.com/krkn-chaos/website/issues/320)) keep those tables current by writing data only, never editing human-written markdown.

&ensp;

## What is here

```
website-template/
  layouts/shortcodes/param-table.html        # renders a parameter table
  layouts/shortcodes/crd-ref.html            # links prose to a generated CRD page
  examples/data/params/<group>/<table>.yaml  # example data files
```

&ensp;

## How it works

A tab file renders its table with one call:

```
{{< param-table scenario="node-scenarios" source="krkn-hub" >}}
```

- reads `data/params/<group>/<table>.yaml`, from the two argument values in that order
- Parameter and Description always show; Type, Possible Values, Default, and Required show only when a row uses them
- missing or empty data calls `errorf`, so a table with no data file fails the build instead of rendering blank
- inherits the site's table styling, no CSS changes

The two arguments name a group and a table within it. What they mean depends on which source wrote the file:

| Source | `scenario=` | `source=` |
| --- | --- | --- |
| krkn-hub | the scenario, or `globals` | the source repo, `krkn-hub` or `krknctl` |
| krkn-operator | the CRD plural | the section, `spec`, `status` or `columns` |

So a generated CRD page calls:

```
{{< param-table scenario="krknscenarioruns" source="spec" >}}
```

Hand-written prose links to those generated pages with the other shortcode, which
resolves the kind and short name from `data/krkn_operator_crds.yaml` rather than
from typed text, so a renamed CRD fails the build instead of leaving a 404:

```
{{< crd-ref crd="krknusers" >}}
```

Data file shape:

```yaml
source_repo: krkn-hub
source_ref: 9f3c1a2
params:
  - name: ACTION                        # required
    description: Action to run.         # required
    type: enum                          # optional
    default: node_stop_start_scenario   # optional
    possible_values: [a, b]             # optional
    required: false                     # optional
```

`name`, `type` and `default` come deterministically from the source. Only
`description` may come from the model.

On a krkn-operator file, `source_repo` holds the section name (`spec`, `status`,
`columns`) rather than a repo, and nothing on it comes from the model at all.

&ensp;

## Installing into the website

1. Copy `layouts/shortcodes/param-table.html` into the website's `layouts/shortcodes/`, and `crd-ref.html` too if the krkn-operator source is in use.
2. Add the `data/params/<group>/<table>.yaml` files.
3. Replace each markdown table in `_tab-<source>.md` with the shortcode call. Surrounding prose stays untouched.

Install the shortcodes before the first data files land. A `param-table` call with no shortcode installed, and a data file with no call, both fail the build.

&ensp;

## Tests

`tests/` holds a Hugo build harness with 14 edge-case tests: column auto-hide,
numeric-zero default, missing and empty data, markdown descriptions, and the
shipped example files. Run with `pytest`.

The bot's own unit tests live in the same folder. They coexist.

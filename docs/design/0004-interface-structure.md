# 0004 — The structure of the interface

- **Status:** proposed on 2026-11-23; the decisions below are open
- **Date:** 2026-11-23
- **Design:** [0001 — Local-first application with a Python service](0001-local-first-architecture.md), decisions 1, 6, 7 and 9, open question "Plugin options in the interface"; [phase 2 plan](0001-phase-2-plan.md), slices 9 and 10 and "Interface changes"

## Question

The interface grew one page at a time while it served the hosted application. Phase 2 replaces the host. In slice 10 it removes the hosted features: visitor counts, the visibility control and project credentials. It keeps every page, path and request. This note decides how the pages of the local application are arranged: what each page is about, where shared parts live, which addresses stay and where explanations come from. It changes no request, record, result format or scientific identity.

## The interface today

The figures below were measured at 1440 × 900 on 5c2a577. The interface was built with `npm run build` and served by the Node host over a QA workspace with 491 records. The records include the cross-head evaluations of example 3.

| Area in the top bar | Tab | Route | Feature | What it does |
| --- | --- | --- | --- | --- |
| Results (`结果库`) | Overview (`实验总览`) | `/` | `features/overview` | Results of the total-area study, and presets that open the design page |
| | Records (`布局记录`) | `/library` | `features/library` | Every record, with filters and the Pareto panel |
| | Comparison (`方案对比`) | `/decision` | `features/decision` | Two records side by side, the position-offset test (`perturb`) and the comparison report |
| | Projects (`研究项目`) | `/projects` | `features/projects` | Projects with owner and viewer credentials, and deliveries |
| | Robustness (`稳健性研究`) | `/robustness` | `features/robustness` | Studies: seed repeats, grid offsets and heads |
| Design (`布局设计`) | Region design (`区域设计`) | `/design` | `features/design` | Radius-constrained search |
| | Electrode editor (`电极编辑`) | `/electrodes` | `features/electrodes` | Copies of a layout with moved or disabled electrodes |
| | Coordinate import (`坐标导入`) | `/coordinates` | `features/decision` with `mode="coordinates"` | Four importers; evaluation under conditions; channel subsets from recordings |
| Signal simulation (`信号仿真`) | — | `/reception` | `features/reception` | Sources, waveforms and artifacts on one layout |
| Documentation (`文档`) | Guide (`使用指南`) | `/guide` | `app/guide` | How to use the application |
| | Method (`建模与原理`) | `/method` | `app/method` | Model, metrics and validation |
| — | — | `/results`, `/pilot-results` | `features/results` | The historical radius batch and the first two-region prototype |
| — | — | `/deliveries` | `features/projects` | Reads a delivery package in the browser, under its own header |

Nine properties make the interface hard to use and to extend:

| # | Property | Effect |
| --- | --- | --- |
| I1 | A layout has no page. Each page names it by its own parameter: `a` and `b` (`/decision`, `/coordinates`), `saved` or `from` (`/design`), `parent` (`/electrodes`) or `record`. The header's current-layout bar reconciles them (`routeSelection` in `lib/workspace-navigation.ts`) and adds `layoutRecord`, `layoutState`, `layoutChannels` and `layoutRegions` to every link | A layout's scores under other conditions, its edited copies and its signal experiments are found only through the library |
| I2 | The values and rules of the evaluation conditions are one contract: `webapp/contracts/scientific-options.mjs`, mirrored in `src/eeglayoutlab/schemas/options.py` and checked by the parity tests. The forms that offer them are built three times. `features/design` builds the noise model and the data prior. `features/decision` builds the noise model, the conductivity scenario, the data prior and cross-session robustness. `features/robustness` builds the noise model, the conductivity scenario and heads | Each new condition needs a form in several features; the noise models of 2026-11 went into all three. Labels and the combinations offered can drift from the contract |
| I3 | Robustness has three entry points that answer different kinds of question. Cross-session robustness is an option of one evaluation (`robustness: "standard/1"`). The position-offset test is one `perturb` request. The studies of `/robustness` are sets of requests | Users choose a page before they choose a question, and the pages do not say which kind they offer |
| I4 | Choosers do not scale. The A and B selects of `/decision` have 117 entries each, many named alike and told apart only by head. The library spreads 491 records over 42 pages. Condition variants are folded by region count and label (`conditionGroupKey` in `lib/records-catalog.ts`), not by coordinates | Finding a layout depends on its name |
| I5 | Pages are long: `/decision` is 11,528 px tall, `/guide` 40,968 px and `/method` 222,635 px | Content past the first screens is rarely reached |
| I6 | Findings and work share a page. `/` is both the landing page and the results of one study (total area, Ernie only). The historical pages are reached only through links on `/` and `/results` | The application opens on one study's results instead of on the user's work |
| I7 | `/coordinates` and `/decision` are one feature in two modes, so the comparison parameters (`a`, `b`, thresholds) appear in the import page's address. The channel-subset tool (`features/data`), which works on recordings, also sits on the import page | Import, comparison and recording analysis cannot change independently |
| I8 | The method has two sources that have diverged. [Model and metrics](../model-and-metrics.md) describes the optional noise models, model mismatch and other heads, cross-session robustness, multi-objective comparison, the data-derived prior and channel subsets. `/method` describes none of these. It still lists other heads, source priors and model mismatch as validation planned for a second stage (`阶段二计划`) | A user of the interface reads a method that is out of date, and every change has to be written twice |
| I9 | Hosted parts remain: the browser-scoped task list and visitor status in the header (`components/community-status.tsx`), the visibility control and project credentials. `/deliveries` has its own header | Slice 10 removes visitor counts, the visibility control and project credentials. The browser-scoped task list and the separate header of `/deliveries` stay |

## Requirements

1. **No science change.** Requests, their normalization, records, result formats and scientific identities stay as they are. The schema and key parity tests pass unchanged.
2. **Stored addresses keep working.** A project's `comparison_href` must be `/decision?` with `a` and `b` (record ids) and optionally `ar`, `thresholdMode`, `sensitivity`, `localization` and `p90` (`features/projects/research-delivery-format.mjs`). Delivery packages carry it. Saved links to the current pages open the equivalent page.
3. **Every page is about one thing:** a layout, a pair of records, a study, a project or a finding.
4. **One implementation per function:** the condition form, robustness and choosing a layout. One function may be offered on more than one page.
5. **One source per explanation.** A topic of the method is written once.
6. **Static pages.** The interface stays a static export (0001, phase 0). There are no dynamic path segments; a page reads its object from the query string.
7. **The showcase uses the same pages,** read-only (0001, decision 1; [showcase](../showcase.md)).
8. **Both languages,** as today.

## Design

### 1. Five areas

The top bar becomes Workspace (`工作区`) · Layouts (`布局`) · Analysis (`分析`) · Findings (`研究结果`) · Documentation (`文档`). "Analysis" avoids a third use of `研究`, which already names projects (`研究项目`) and robustness studies (`稳健性研究`).

| Area | Pages | Replaces |
| --- | --- | --- |
| Workspace | `/`: the workspace home. `/projects`. `/deliveries`, opened from here in the common frame | The overview as landing page, the header's task list |
| Layouts | `/library`, listing layouts. `/layout?key=` (new). New layout: `/design` (search by regions), `/coordinates` (import). `/electrodes` (editor), opened from a layout | The `结果库` records tab and the `布局设计` area |
| Analysis | `/decision` (comparison), `/robustness` (studies), `/reception` (signal simulation of one layout), `/channels` (channel subsets from recordings, new) | Comparison, robustness and simulation spread over three areas |
| Findings | `/findings` (new): the total-area study, today's `/`. `/results` and `/pilot-results`, listed there as historical batches | Results reached only from the landing page |
| Documentation | `/guide`. The method in the documentation (section 8) | `/method` as a second source |

The showcase has no workspace, so it shows the other four areas.

### 2. The layout page

`/layout?key=<layout key>` shows one layout. `/layout?id=<record id>` opens the layout of that record.

- **Layout key.** The key is the SHA-256 of the JSON text of `{xyz_mm, region_indices}` in Ernie native millimetres, the coordinates of `eeg-electrode-design/1`.
  - For a coordinate evaluation, the coordinates come from the request's `design`; for a search, from the result's layout.
  - A head's mapped positions never enter the key, so the evaluations of one design on eleven heads share one key.
  - A search result evaluated again from its record (as `/decision` does) has the same key. So has an import of its exported coordinates, when the export keeps the stored numbers.
  - The design name does not enter the key.
  - An edited copy has its own key and points to its parent through `parent_id`, as today.
- **Where the key is computed.** The interface computes it from a draft's coordinates. The service computes it for records and adds it to library summaries as `layout_key`, so the library can be listed and searched by layout. The key is never stored in a record and enters no scientific identity.
- **Header.** Name, electrode and region count, and origin: search, import, or edit of another layout. A layout without an evaluation is shown as a draft; it has a key, so its page stays the same once it is evaluated.
- **View.** The 3D head and the coordinate table, with the existing exports.
- **Evaluations.** One row per record of the layout: condition labels (`recordConditionLabels`), the three retention scores and the threshold judgement. The nominal Ernie evaluation comes first.
- **Related.** Edited copies, signal experiments, robustness studies and projects that include the layout.
- **Actions.** Evaluate under a condition, the position-offset test, compare with another record, start a robustness study, simulate signals, copy and edit, add to a project, export.

The other pages link to the layout page instead of passing their own selection parameters. The header's current-layout bar becomes the layout page's breadcrumb.

### 3. New layouts

"New layout" is one menu with two sources, plus copying from a layout page:

- **Search by regions:** `/design`, with the presets that sit on today's `/` ("按部位创建布局").
- **Import coordinates:** `/coordinates` with one file input that recognizes the format. The formats are:
  - CSV or JSON, with or without a region column;
  - a BIDS `electrodes.tsv` with `coordsystem.json`;
  - `.elc` and `.sfp`, asking the unit for `.sfp`;
  - a list of 10-05 names.

  Today these are four inputs. In phase 4 the formats come from `eeglayoutlab.coordinate_formats` (0001, decision 9). The import page no longer carries comparison parameters (I7).
- **Copy and edit:** from a layout page into `/electrodes`.

Each ends on the layout page. Until the workspace stores drafts (0001, decision 7: "saved layouts"), a draft lives in the address, as today.

### 4. Evaluation conditions

One component, `EvaluationConditions`, offers the conditions for one action: search, evaluate, `perturb` or a study protocol. It adds no rules of its own.

- **Values** come from `scientific-options.mjs`:
  - `NOISE_MODEL_PRESETS` (five noise models);
  - `CONDUCTIVITY_SCENARIOS` (two, besides the default);
  - the heads listed by `GET /api/design-evaluation/heads`;
  - the data prior (`eeg-data-prior/1`);
  - `ROBUSTNESS_PROTOCOL`.
- **What may be offered** is decided by the contract's own normalizers: `normalizeNoiseModel`, `normalizeConductivityScenario`, `normalizeHeadId`, `normalizeRobustness` and `normalizeDataPrior`. They take the action or the other choices, so the component offers only combinations the service accepts. Today these are:
  - the brain-background noise model in design evaluation, not in the radius search;
  - a conductivity scenario and a head with `evaluate` and in studies, never with `perturb`;
  - cross-session robustness with `evaluate` only, and not with a conductivity scenario or a head;
  - the data prior, which excludes a noise model and a head.
- **Labels** come from the contract's label functions (`noiseModelLabel`, `conductivityScenarioLabel`, `dataPriorLabel`) and the i18n catalogs. The same labels mark records everywhere.
- **Defaults** are omitted from the request exactly as today (requirement 1).

A new condition is then added to the contract and its Python mirror, and appears in every form. In phase 4 an extension's declared options enter the same contract. This is the interface's side of 0001's open question "Plugin options in the interface".

### 5. Analysis

- **Comparison** stays at `/decision` with its parameters (requirement 2). The two selects become one chooser per side, with search and filters. Each lists layouts by `layout_key`, then the records of the chosen layout by condition, and sets `a` or `b` to that record.
- **One request or several.** A question that one request answers is an action on the layout page:
  - an evaluation under a condition;
  - cross-session robustness, which is an option of that evaluation;
  - the position-offset test (`perturb`).

  The comparison page offers the same actions for its two records. The offset test's result stays in the comparison report, which appends the latest result (`decisionMarkdown`). A question that needs a set of requests is a study on `/robustness`: seed repeats, grid offsets and heads. Each sends the requests it sends today.
- **Signal simulation** keeps `/reception?record=` and is entered from the layout page.
- **Channel subsets.** The tool that chooses channel subsets from recording summaries moves from `/coordinates` to `/channels`.

### 6. Workspace and projects

- **Workspace home.** `/` shows the workspace's queue (0001, decision 6), recent layouts, studies and projects. It replaces the browser-scoped task list in the header.
- **Projects.** Slice 9 moves projects into the workspace and slice 10 removes credentials. This note only places them under Workspace.
- **Deliveries.** `/deliveries` uses the common frame. It still works without a service.

### 7. Findings

- `/findings` holds the total-area study, today's `/`, with its parameters (`domain`, `area`, `r`, `metric`, `ar`).
- `/results` and `/pilot-results` keep their paths and are listed on `/findings` as historical batches, each with its protocol and date.
- In the showcase, `/` opens `/findings`.

### 8. Documentation

- **The method has one source:** the Markdown under `docs/` ([model and metrics](../model-and-metrics.md), [validation](../validation.md), [robustness studies](../robustness-studies.md)). Topics that only `/method` covers, such as the pilot and the historical batches, move there. Its validation plan is replaced by [validation](../validation.md).
- **Offline.** The application works without a network, so the package includes the built documentation site, and the local service serves it under `/docs/`. The showcase links to the published site.
- **In the interface.** Each page keeps a short explanation of what it shows, bilingual, as `RetentionExplainer` and `SimulationExplainer` do today. Each explanation links to its chapter. `/method` becomes an index of those chapters, and its old `#section` links open the chapter that took the section over.
- **Guide.** `/guide` stays in the interface, bilingual, rewritten for the five areas with one short section per task.
- **Chinese.** The method chapters are in English, as the paper is. Chinese chapters can be added beside them, as for installation (`*.zh-CN.md`).

### 9. Addresses

| Today | After |
| --- | --- |
| `/` with overview parameters | `/findings` with the same parameters |
| `/` without parameters | The workspace home |
| `/library?record=` of a search, coordinate evaluation or edited copy | `/layout?id=` |
| `/library?record=` of a signal experiment | Unchanged |
| `/method#<section>` | The chapter that took the section over |
| `/coordinates` with `a`, `b` or thresholds | `/coordinates` without them |
| `layoutRecord`, `layoutState`, `layoutChannels`, `layoutRegions` on any page | Ignored; new links no longer add them |
| Every other path and parameter, including `/decision` | Unchanged |

Redirects run in the page, since the interface is static. They stay for the 0.x series.

### 10. Order of work

1. **Now, on either host.** None of these changes an address that is stored or a request flow.
   - the conditions component (I2);
   - the chooser on `/decision` (I4), first by record and then by layout once `layout_key` exists;
   - `/channels`, and comparison parameters out of `/coordinates` (I7);
   - the method in one source (I8): the topics that only `/method` covers are written into `docs/`.
2. **After slice 10, before the phase 3 release:**
   - `layout_key`, `/layout` and a layout-first library (I1, I4);
   - the workspace home, `/findings`, the five-area top bar and the redirects (I6);
   - the actions of section 5 (I3);
   - `/deliveries` in the common frame (I9).

   Slice 10 must show that every browser workflow passes against the Python service. Changing the pages at the same time would leave a failure ambiguous between the host and the interface.
3. **With phase 3:**
   - the documentation in the package and `/docs/` in the service;
   - the showcase on the new structure;
   - the guide rewritten.

**Tests.**
- The browser workflows (`scripts/check-workflows-browser.mjs`) follow the new pages.
- The i18n check covers the new labels.
- The contract and parity tests pass unchanged (requirement 1).
- New tests check that:
  - each old address opens its new page;
  - the interface and the service compute the same `layout_key`;
  - the condition form offers exactly the combinations that the contract's normalizers accept.

## Consequences

- A new condition, importer or robustness protocol is added in one place.
- The library lists layouts; a record view remains for audits.
- `layout_key` is a new field of the library API, though not of any record or identity.
- The phase 3 package grows by the built documentation, and its build needs MkDocs.
- The full method is in English until Chinese chapters are written; the per-page explanations stay bilingual.
- Redirect code stays in the interface until 1.0.
- Screenshots and wording in the guide and in `docs/` that name the old areas need updating.

## Decisions

Open; each has a recommendation.

1. **Five areas:** Workspace, Layouts, Analysis, Findings, Documentation (section 1). Recommended.
2. **A layout page at `/layout?key=`.** The key is the SHA-256 of the Ernie-native `{xyz_mm, region_indices}`. It is computed by the interface and the service, never stored, and enters no identity (section 2). Recommended.
3. **Paths stay except `/`.** `/` becomes the workspace home. `/layout`, `/findings` and `/channels` are new. Old overview addresses redirect, and selection parameters are dropped (sections 1 and 9). Recommended.
4. **One condition form on top of the existing contract.** It takes values, rules and labels from `scientific-options.mjs` and adds none of its own (section 4). Recommended.
5. **One request is an action, several are a study.** Cross-session robustness and the offset test are actions of the layout and comparison pages; repeats and heads are studies on `/robustness` (section 5). Recommended.
6. **The method has one source in `docs/`.** The service serves it offline; the interface keeps short bilingual explanations that link to it (section 8). Recommended. The alternative is to keep `/method` as the bilingual source and bring it up to date with `docs/`. That keeps Chinese, but every change is written twice.
7. **Order:** stage 1 now; stage 2 after slice 10 and before the phase 3 release; stage 3 with phase 3 (section 10). Recommended.

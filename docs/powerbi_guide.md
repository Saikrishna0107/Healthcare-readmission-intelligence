# Building the report pages (step 9c)

A click-by-click guide for the four report pages (the Checks page is step 9b) of `powerbi/HRI.pbip`. The data, the model and
every measure already exist (steps 9a and 9b); these pages only arrange them. Build one page,
save (Ctrl+S), check it, then go on.

Names in **bold** are what you click or type. `Table[column]` means a column in the Data pane:
expand the table, tick the column. Measures have a calculator icon and sit in display folders.

Conventions for every page:
- Page size stays 16:9. Put a **text box** title at the top left (Insert > Text box).
- Every visual gets a title that says what it shows, not how (Format visual > General > Title).
- When a visual should *not* follow a slicer, use **Edit interactions** (step explained on page 1).

Traps met while building the first version (each one gave a wrong number, not just a look):
- **Measures are in folders** (Penalty, Patient survey, Readmissions, Model, Checks), below the
  columns. Ticking a *column* such as `is_penalized` or `counts_toward_penalty` instead of the
  measure counts every row; the subtitle then reads "Count of …".
- **Edit interactions belongs to the slicer**: select the slicer first, then set *None* on the
  trend. Set on another visual, the trend still shows a single year.
- **Sort a trend by fiscal_year**, ascending (… > Sort axis). Sorted by value, years run out of
  order.
- **Text in Card (new) goes into the Value well, dragged**, not ticked: ticked text lands in
  Categories, which draws one tile per hospital.
- Large numbers show as 3K by default: Format visual > Callout value > Display units > None.

Traps met while polishing it for screenshots:
- **A title must match the filter.** The page 1 table is the top 20 by largest payment cut, so
  it is "20 largest payment cuts", sorted by the cut. Titled "at the 3% cap", it listed 2.62%.
- **Export to PDF prints the current selection.** A clicked bar or row cross-filters the page
  (cards showed 1 hospital, 100% penalized). Click empty canvas before exporting.
- **Card (new) labels are cut at about 9 characters** when five cards share one row. Shorter
  labels (in the Data well, the field's menu > Rename for this visual) fixed it; a
  3-column grid made the tiles overflow, and the export shrank the whole page to fit them.
- **Smoothed lines draw values that don't exist** between years. Use straight lines
  (Format visual > Lines > Interpolation type > Linear).

---

## Page 1 · Penalty overview

*Question it answers: how many hospitals does Medicare penalize, by how much, and where?*

1. **Rename** the page: right-click the tab at the bottom, *Rename*, type `Penalty overview`.
   (Add it with **+** next to *Checks*; drag the tab left of *Checks* so Checks is last.)
2. **Title**: Insert > Text box: `Hospital Readmissions Reduction Program — penalties`.
3. **Year slicer**
   - Click empty canvas, Visualizations > **Slicer**, tick `Fiscal year[fiscal_year]`.
   - Format visual > Visual > Slicer settings > Options > Style: **Dropdown**;
     Selection: **Single select** on.
   - Pick **FY2026** in the slicer.
4. **Headline numbers**
   - Click empty canvas, **Card (new)** (the card icon you used on Checks).
   - Tick, from *Hospital year*: **Hospitals in the payment file**, **Penalized hospitals**,
     **Share of hospitals penalized**, **Average payment reduction (penalized hospitals only)**,
     **Hospitals at the 3% cap**.
   - Place it as a band across the top.
5. **Trend line**
   - Click empty canvas, **Line chart**. X-axis: `Fiscal year[fiscal_year]`.
     Y-axis: **Share of hospitals penalized**.
   - Title: `Share of hospitals penalized, by fiscal year`.
   - **Edit interactions** (the trend must show every year, whatever the slicer says):
     click the **slicer**, ribbon **Format > Edit interactions**. Small icons appear on the
     other visuals; on the line chart click the **None** icon (circle with a line through it).
     Click **Edit interactions** again to finish.
6. **By state**
   - Click empty canvas, **Clustered bar chart**. Y-axis: `Hospital[state]`.
     X-axis: **Share of hospitals penalized**.
   - Sort: the visual's **...** > Sort axis > **Share of hospitals penalized**, Sort descending.
   - Title: `Share penalized, by state`.
7. **Hospitals with the largest penalty**
   - Click empty canvas, **Table**. Columns: `Hospital[facility_id]`, `Hospital[facility_name]`,
     `Hospital[state]`, **Largest payment reduction**.
   - Top 20 only: in the Filters pane under *Filters on this visual*, expand **facility_id**,
     Filter type **Top N**, Show items **Top 20**, By value: drag **Largest payment reduction**
     into the box, **Apply filter**.
   - Sort by *Largest payment reduction*, largest first. Title: `20 largest payment reductions`.
8. **Ctrl+S**.

Check: with FY2026 selected, the card and the line chart's FY2026 point show the same share.
Maryland is not in the bar chart's numbers: its hospitals are exempt from HRRP.

---

## Page 2 · Conditions

*Question: which of the six conditions drive readmission penalties?*

1. **A readable condition name** (your first DAX column)
   - Data pane: right-click **Readmission results** > **New column**. In the formula bar type:
     ```
     condition_name = SWITCH('Readmission results'[condition],
         "AMI", "Heart attack (AMI)", "HF", "Heart failure", "PN", "Pneumonia",
         "COPD", "COPD", "CABG", "Bypass surgery (CABG)", "HIP_KNEE", "Hip/knee replacement",
         'Readmission results'[condition])
     ```
   - Press Enter. The last argument keeps any future code visible instead of blank.
2. New page `Conditions`, with a title text box.
3. **Same year slicer, synced**: on *Penalty overview* click the slicer, Ctrl+C; on *Conditions*
   Ctrl+V. Power BI asks whether to **Sync**: choose **Sync**. Changing the year on one page
   now changes it on both (see View > Sync slicers).
4. **What counts toward the penalty, by condition**
   - **Clustered bar chart**. Y-axis: `Readmission results[condition_name]`.
     X-axis: **Results counting toward the penalty**. Sort descending.
   - Title: `Hospital results counting toward the penalty, by condition`.
5. **Condition × year**
   - **Matrix**. Rows: `condition_name`. Columns: `Fiscal year[fiscal_year]`.
     Values: **Share of results worse than expected**.
   - Colour: Values well > **Share of results worse than expected** > dropdown arrow >
     Conditional formatting > **Background color** > OK (default gradient).
   - Edit interactions: slicer > **None** on the matrix (it shows all years).
   - Title: `Share worse than expected, by condition and year`.
6. **Volume card**: **Card (new)** with **Scored results**, **Results counting toward the
   penalty**, **Eligible discharges**.
7. **Ctrl+S**.

What the numbers mean: the Excess Readmission Ratio compares a hospital's readmissions with
what CMS expects for *its* patients. Above 1 = more than expected. "Expected" is the national
average for similar patients, so about half of all results are above 1 by construction (48.6% in
this data, 48-50% for every condition). The share therefore says little on its own; how many
results count toward a penalty (ratio above the peer-group median, enough cases) differs more.

---

## Page 3 · Hospital detail (drill-through)

*Question: why is this one hospital penalized, and what does the model say about it?*

1. New page `Hospital detail`, with a title text box.
2. **Make it a drill-through page**
   - Click empty canvas. In Visualizations > Build visual, scroll to **Drill through**.
   - Drag `Hospital[facility_id]` into **Add drill-through fields here**.
   - **Keep all filters: Off** (the page should show every year, not only the slicer's year).
   - Power BI adds a back arrow at the top left; leave it.
3. **Who it is**: **Card (new)**; *drag* `Hospital[facility_name]`, `Hospital[city]`,
   `Hospital[state]`, `Hospital[hospital_type]` into the **Value** well (not Categories). Text
   columns show as *First …*: a card needs one value, and with one hospital that is its value.
4. **Penalty by year**: **Line chart**, X-axis `Fiscal year[fiscal_year]`, Y-axis
   **Average payment reduction (all hospitals in the file)**. Title: `Payment reduction by year`.
5. **Every condition result**: **Table** with `Readmission results[fiscal_year]`,
   `condition_name`, `excess_readmission_ratio`, `peer_group_median_err`,
   `counts_toward_penalty`. Sort by fiscal_year, newest first.
   Title: `Condition results (ratio vs peer-group median)`.
6. **The model's view (FY2026)**
   - **Card (new)**: **Predicted payment reduction**, **Actual payment reduction (model rows)**.
   - **Clustered bar chart**: Y-axis `Model drivers[family]`, X-axis **Driver contribution**.
     Title: `What moved the prediction (percentage points)`.
7. **Ctrl+S**, then **test it**: on *Penalty overview*, right-click a hospital in the top-20
   table > **Drill through > Hospital detail**. Ctrl+click the back arrow to return.

How to read the drivers: the model starts from the average prediction; each bar is how far one
feature family (survey scores, volume, county health, patient mix, hospital profile) pushed
this hospital's prediction up or down. Bars plus the start add up to the prediction.

---

## Page 4 · Model risk

*Question: which hospitals does the model expect to be among the most penalized, and how often
is it right?*

1. New page `Model risk`, title `FY2026 penalty-risk model (step 7)`. No year slicer here:
   the model has predictions for FY2026 only.
2. **Text box** under the title:
   `A hospital is flagged when its predicted payment reduction is in the top quarter. The
   prediction uses only data available before the penalty is published.`
3. **Card (new)**: **Hospitals flagged**, **Flagged hospitals actually in the top quarter**.
4. **Predicted vs actual**
   - **Scatter chart**. X-axis: **Actual payment reduction (model rows)**. Y-axis:
     **Predicted payment reduction**. Values: `Hospital[facility_id]` (one dot per hospital).
   - Title: `Predicted vs actual payment reduction, FY2026 (%)`.
5. **Flagged hospitals**
   - **Table**: `Hospital[facility_id]`, `Hospital[facility_name]`, `Hospital[state]`,
     **Predicted payment reduction**, **Actual payment reduction (model rows)**.
   - Filters on this visual: drag `Model risk[is_flagged]` in, tick **True**.
   - Sort by *Predicted payment reduction*, largest first. Right-click a row > Drill through
     works here too.
6. **Ctrl+S**.

Honest reading: about half the flagged hospitals really end up in the top quarter, twice the
25% of guessing at random. Good enough to prioritise reviews, not to decide anything alone.

---

## When you are done

Send a screenshot of each page. The page files in `powerbi/HRI.Report/definition/pages/` are
reviewed in git like code.

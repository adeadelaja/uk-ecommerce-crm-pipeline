# Project Nexus | Phase 3: Power BI Build Guide

**Goal:** a three page dashboard that reconciles to the penny with Phase 1 (Python) and Phase 2 (SQL).
**Baseline:** 5,000 record simulation, tag `checkpoint-02`.
**You need open:** Power BI Desktop, VS Code with `powerbi/measures.dax`, and this guide.
**Time:** about 2 to 3 hours. Every stage ends with a check, so you can stop after any stage and pick up later.

| Stage | What you build | Check before moving on |
|---|---|---|
| 1 | Settings and theme | Theme applied |
| 2 | Load and clean four tables | Row counts match |
| 3 | Calendar, relationship, parameter | Model view looks right |
| 4 | 20 measures | 16 validation cards match |
| 5 | Page 1: Revenue Leakage | Bar chart totals £424,692 |
| 6 | Page 2: Pipeline Forecast | Expected revenue £628,639 |
| 7 | Page 3: Data Quality | Pass rate 83.8% |
| 8 | Polish, export, commit | Pushed to GitHub |

---

## Stage 1: Settings and theme

1. Open Power BI Desktop and start a **Blank report**.
2. **File > Options and settings > Options**, then:
   * **Current File > Data Load:** untick **Auto date/time**. We build our own Calendar, and auto date tables bloat the model.
   * **Current File > Regional Settings:** set locale to **English (United Kingdom)** so £ formats correctly.
3. Save straight away: **File > Save as** to `powerbi/Project_Nexus_Dashboard.pbix`.
4. Save `nexus_theme.json` into your `powerbi/` folder, then **View > Themes > Browse for themes** and select it. Charts now default to slate grey, with red kept for leakage.

**Check:** the canvas is white and the first chart colour in the palette is grey.

---

## Stage 2: Load and clean the data

### 2.1 Load all four files
**Home > Get data > Text/CSV**. For each file, click **Transform Data** (not Load):

| Rename query to | File | Rows expected |
|---|---|---|
| `FactPipeline` | `data/processed/clean_crm_migration.csv` | 4,274 |
| `Quarantine` | `data/quarantine/rejected_records.csv` | 826 (before split) |
| `Hygiene` | `data/processed/sql_3a_data_hygiene_scorecard.csv` | 10 |
| `HygieneDetail` | `data/processed/sql_3b_data_hygiene_detail.csv` | varies |

Once Power Query is open, use **Home > New Source > Text/CSV** for the next file. Rename a query by double clicking it in the left panel.

### 2.2 Clean `FactPipeline`
1. Set types: click the type icon on each column header, and choose **Replace current** if asked.

| Column | Type |
|---|---|
| Transaction_Timestamp | Date/Time |
| Revenue_Amount_GBP | Fixed decimal number |
| Leakage_GBP | Fixed decimal number |
| Response_Time_Hours | Whole number |
| Stage_Inferred | True/False |
| Is_Closed_Lost | True/False |
| Everything else | Text |

2. Right click `Friction_Reason` > **Replace Values**: find `None`, replace with `No Friction`.
3. Select `Transaction_Timestamp` > **Add Column > Date > Date Only**. Rename the new column `Transaction_Date`.

### 2.3 Clean `Quarantine`
1. **Add Column > Index Column > From 1**. Rename it `Record_ID`. This must happen **before** step 2, so each record keeps one ID after it is split.
2. Right click `Rejection_Reason` > **Split Column > By Delimiter** > Custom: `;` > open **Advanced options** > **Split into Rows**.
3. Optional: remove the columns you won't chart (Customer_UUID, Revenue_Amount_GBP and so on). Keep `Record_ID`, `Rejection_Reason` and `raw_log`.

### 2.4 `Hygiene` and `HygieneDetail`
No changes needed. Check that `Failing_Rows` is Whole number and `Revenue_Amount_GBP` is Fixed decimal.

**Home > Close & Apply.**

**Check:** in Table view (left sidebar, grid icon), `FactPipeline` shows **4,274 rows** in the status bar at the bottom.

---

## Stage 3: Model

### 3.1 Measures table
**Home > Enter data** > name it `_Measures` > **Load**. Every measure lives here, which is what a reviewer looks for. Once your first measure is in, delete the default `Column1`.

### 3.2 Calendar
**Modeling > New table**, paste the `Calendar = ...` block from `measures.dax`, and press Enter.
Then **Table tools > Mark as date table** > select `Date`.
Select `Month` in the Calendar fields > **Column tools > Sort by column > Month Start**, so months sort in date order instead of alphabetically.

### 3.3 Relationship
**Model view** (left sidebar). Drag `Calendar[Date]` onto `FactPipeline[Transaction_Date]`.
Double click the line to confirm it is **One to many (1:*)**, cross filter **Single**.

### 3.4 What if parameter
**Modeling > New parameter > Numeric range**:

| Setting | Value |
|---|---|
| Name | Recovery Rate |
| Data type | Decimal number |
| Minimum | 0 |
| Maximum | 1 |
| Increment | 0.05 |
| Default | 0.5 |
| Add slicer to this page | ticked |

This creates a table `Recovery Rate` with a measure `[Recovery Rate Value]`. Select that measure and format it as **Percentage**.

**Check:** Model view shows `Calendar` linked to `FactPipeline`, with `Quarantine`, `Hygiene`, `HygieneDetail`, `_Measures` and `Recovery Rate` standing alone. Those standalone tables are correct: they don't need relationships.

---

## Stage 4: Measures

1. Select `_Measures` in the Data pane > **New measure**.
2. Paste **one measure at a time** from `measures.dax`, starting at `Total Pipeline £`, and press Enter after each.
3. Format each one from the **Measure tools** ribbon:
   * **£ measures:** Currency > **£ English (United Kingdom)**, 0 decimals
   * **% measures:** Percentage, 1 decimal
   * **Count measures:** Whole number, thousands separator on
   * `Avg Response Hrs (Lost to Delay)`: Decimal, 1 place
4. `Hygiene Status Colour` returns colour codes. Leave it unformatted, because it only drives conditional formatting.

### Validation page
Add a page called `Validation`. Put each measure on its own **Card** with no slicers. Every card must match:

| Measure | Expected |
|---|---|
| Total Pipeline £ | £1,178,155 |
| Deal Count | 4,274 |
| Leakage £ | £424,692 |
| Leakage % | 36.0% |
| Lost Deals | 1,480 |
| Avg Response Hrs (Lost to Delay) | 86.4 |
| SLA Breach % | 18.3% |
| Won Revenue £ | £554,167 |
| Open Pipeline £ | £199,296 |
| Weighted Open £ | £74,472 |
| Expected Revenue £ | £628,639 |
| Open Deals At Risk | 115 |
| Win Rate % | 57.8% |
| Recoverable Revenue £ (slider at 50%) | £80,633 |
| Quarantined Records | 826 |
| Pipeline Pass Rate % | 83.8% |

If a card is wrong, the usual causes are:

| Symptom | Likely cause |
|---|---|
| £ values far too high | Revenue left as Text, or Quarantine joined to the model |
| Open Deals At Risk shows 0 | Friction_Reason values have trailing spaces (Transform > Trim) |
| Quarantined Records shows 1,441 | Index column added after the split instead of before |
| Recoverable Revenue blank | The parameter slicer has no value selected |
| SLA Breach % wrong | Response_Time_Hours left as Text |

Keep this page hidden in the final version (right click the tab > **Hide page**). Interviewers like it as evidence of reconciliation.

---

## Stage 5: Page 1, Revenue Leakage

Rename Page 1: `Revenue Leakage`.

| Zone | Visual | Fields |
|---|---|---|
| Title (top) | Text box | **"Response delays are the largest single leak: £161k of £425k lost"** |
| KPI row | 4 Cards | Total Pipeline £, Leakage £, Leakage %, Lost Deals |
| Main left | Clustered bar chart | Y axis `FactPipeline[Friction_Reason]`, X axis `Leakage £`, Tooltips `Leakage Share of Total %` and `Lost Deals` |
| Main right | Matrix | Rows `Region`, Columns `Friction_Reason`, Values `Leakage £` |
| Bottom right | Slicer + Card | `Recovery Rate` slicer; card `Recoverable Revenue £` titled "Revenue recovered by fixing response delays" |
| Left rail | 3 Slicers | `Channel`, `Product_Category`, `Calendar[Month]` (dropdown style) |

Formatting:
* **Bar chart:** sort descending by Leakage £ (the ... menu > Sort axis), data labels on, colour all bars grey, then under **Bars > Colors**, turn on **Show all** and set **Response Delay** to red `#C62828`.
* **Matrix:** **Cell elements > Background color > fx** > Gradient, lowest white, highest red. Manchester should stand out at about £53k.
* **No Friction** won't appear in the bar chart, because those rows carry no leakage. That's correct.

**Check:** hover over the bars. The four values add to £424,692, and Response Delay shows 38.0%.

---

## Stage 6: Page 2, Pipeline Forecast

New page: `Pipeline Forecast`.

| Zone | Visual | Fields |
|---|---|---|
| Title | Text box | **"£629k expected revenue; 115 open deals already showing friction"** |
| KPI row | 5 Cards | Open Pipeline £, Weighted Open £, Expected Revenue £, Win Rate %, Open Deals At Risk |
| Main | Line and clustered column chart | X axis `Calendar[Month Start]`, Column y axis `Won Revenue £`, Line y axis `Weighted Open £` |
| Bottom | Table | `Transaction_ID`, `Region`, `Channel`, `Friction_Reason`, `Revenue_Amount_GBP` |
| Footnote | Text box | "Forecast weights: Open 40%, reduced for friction (delay x0.5, stockout x0.4, navigation x0.6). Illustrative; calibrate on historic win rates." |

Formatting:
* On the X axis field `Month Start`, click the dropdown arrow and choose **Month Start** (not Date Hierarchy) so the axis shows one continuous timeline.
* **Table visual filters:** in the Filters pane for this visual, set `Deal_Stage` is **Open**, and `Friction_Reason` is not **No Friction**. Sort by `Revenue_Amount_GBP` descending, and title it "At risk deals to chase this week".
* **Columns:** grey. **Line:** red.

**Check:** the at risk table shows 115 rows (row count is in the visual's ... menu > Show as table).

---

## Stage 7: Page 3, Data Quality

New page: `Data Quality`.

| Zone | Visual | Fields |
|---|---|---|
| Title | Text box | **"83.8% of raw records passed; 826 quarantined with audit codes"** |
| KPI row | 3 Cards | Pipeline Pass Rate %, Quarantined Records, Hygiene Checks Failing |
| Main left | Clustered bar chart | Y axis `Quarantine[Rejection_Reason]`, X axis `Rejection Reason Count` |
| Main right | Table | `Hygiene_Check`, `Failing_Rows`, `Failing_Pct`, `Status` from `Hygiene` |
| Bottom | Table | All columns from `HygieneDetail`, sorted by `Revenue_Amount_GBP` descending |

Formatting:
* **Status colours:** select the Hygiene table > **Format > Cell elements** > Series: **Status** > **Font color** on > **fx** > Format style **Field value** > based on field `Hygiene Status Colour`. PASS turns green, WARN amber, FAIL red.
* Rename the `Failing_Pct` column header in the visual to `Failing %`. It's already a percentage figure, so don't apply % formatting on top.

**Check:** bars read Unparseable revenue 365, Invalid customer UUID 303, Unparseable date 283, Unknown deal stage 268, Duplicate txn 106, Missing txn ID 80, Empty row 36.

---

## Stage 8: Polish, export, commit

### Polish checklist
- [ ] All three page titles state a finding, not a label
- [ ] Every £ shows the pound sign; no decimals on cards
- [ ] Red is used only for leakage or risk
- [ ] Slicers on Page 1 also filter Page 2 (**View > Sync slicers**, tick both pages for Channel and Category)
- [ ] Validation page hidden
- [ ] A small footer text box on each page: "Harrize | Project Nexus | Simulated data, 5,000 records"

### Export evidence for the README
1. Take a screenshot of each page (**Win + Shift + S**) and save to `docs/images/` as `page1_leakage.png`, `page2_forecast.png` and `page3_quality.png`.
2. **File > Export > Export to PDF**, saved as `docs/Project_Nexus_Dashboard.pdf`.

### Commit (one line at a time)
```powershell
git add powerbi/ docs/
```
```powershell
git commit -m "Phase 3: Power BI dashboard, DAX measures, theme and screenshots"
```
```powershell
git push
```
```powershell
git tag -a checkpoint-03 -m "Phase 3 complete: dashboard reconciles to £424,692.27 leakage"
```
```powershell
git push origin checkpoint-03
```

**Phase 3 is done when** all 16 validation cards match, the three pages are built, and `checkpoint-03` is on GitHub. Send the three screenshots for review before Phase 4.

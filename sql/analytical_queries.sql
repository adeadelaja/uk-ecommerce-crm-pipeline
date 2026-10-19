/* ============================================================================
   Project Nexus | Phase 2: Relational SQL Analytics Layer
   Harrize Consulting | UK E-Commerce Revenue Leakage & CRM Ingestion Pipeline

   Engine     : SQLite 3.35+ (ships with Python; zero install)
   Source     : data/processed/clean_crm_migration.csv (Phase 1 output)
   Executed by: src/db_loader.py, which runs each "-- @block:" in order and
                bulk loads the CSV into stg_crm_migration after the schema block.

   Typing note: SQLite uses type affinity, so strictness is enforced with
   CHECK constraints (typeof, GLOB patterns, domain lists). Declared types
   mirror the enterprise target (PostgreSQL / SQL Server) for portability.
   ============================================================================ */


-- @block: schema
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS uk_ecommerce_pipeline;
DROP TABLE IF EXISTS stg_crm_migration;

/* Landing zone: everything arrives as TEXT, exactly as Phase 1 wrote it. */
CREATE TABLE stg_crm_migration (
    Transaction_ID         TEXT,
    Transaction_Timestamp  TEXT,
    Customer_UUID          TEXT,
    Revenue_Amount_GBP     TEXT,
    Deal_Stage             TEXT,
    Channel                TEXT,
    Region                 TEXT,
    Product_Category       TEXT,
    Response_Time_Hours    TEXT,
    Interaction_Note       TEXT,
    Friction_Reason        TEXT,
    Stage_Inferred         TEXT,
    Is_Closed_Lost         TEXT,
    Leakage_GBP            TEXT
);

/* Governed analytical table with strict, enforced types. */
CREATE TABLE uk_ecommerce_pipeline (
    Transaction_ID         VARCHAR(12)    NOT NULL PRIMARY KEY
                           CHECK (Transaction_ID GLOB 'TXN[0-9][0-9][0-9][0-9][0-9][0-9]'),
    Transaction_Timestamp  DATETIME       NOT NULL
                           CHECK (Transaction_Timestamp = datetime(Transaction_Timestamp)),
    Customer_UUID          CHAR(36)       NOT NULL
                           CHECK (length(Customer_UUID) = 36
                                  AND Customer_UUID GLOB '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-*-*-*-*'),
    Revenue_Amount_GBP     DECIMAL(12,2)  NOT NULL
                           CHECK (typeof(Revenue_Amount_GBP) IN ('real','integer') AND Revenue_Amount_GBP > 0),
    Deal_Stage             VARCHAR(12)    NOT NULL
                           CHECK (Deal_Stage IN ('Closed-Won','Closed-Lost','Open')),
    Channel                VARCHAR(20)    NOT NULL,
    Region                 VARCHAR(30)    NOT NULL,
    Product_Category       VARCHAR(30)    NOT NULL,
    Response_Time_Hours    SMALLINT       NULL
                           CHECK (Response_Time_Hours IS NULL
                                  OR (typeof(Response_Time_Hours) = 'integer' AND Response_Time_Hours >= 0)),
    Interaction_Note       VARCHAR(255)   NULL,
    Friction_Reason        VARCHAR(25)    NULL
                           CHECK (Friction_Reason IS NULL OR Friction_Reason IN
                                  ('Response Delay','Warehouse Stockout','Navigation Friction','Unattributed')),
    Stage_Inferred         BOOLEAN        NOT NULL CHECK (Stage_Inferred IN (0,1)),
    Is_Closed_Lost         BOOLEAN        NOT NULL CHECK (Is_Closed_Lost IN (0,1)),
    Leakage_GBP            DECIMAL(12,2)  NOT NULL
                           CHECK (typeof(Leakage_GBP) IN ('real','integer') AND Leakage_GBP >= 0),
    Loaded_At              DATETIME       NOT NULL DEFAULT (datetime('now')),

    /* Business rule: leakage exists only on lost deals and equals deal value */
    CHECK ((Is_Closed_Lost = 1 AND Leakage_GBP = Revenue_Amount_GBP)
        OR (Is_Closed_Lost = 0 AND Leakage_GBP = 0)),
    CHECK ((Deal_Stage = 'Closed-Lost') = (Is_Closed_Lost = 1))
);

CREATE INDEX ix_pipeline_stage_friction ON uk_ecommerce_pipeline (Deal_Stage, Friction_Reason);
CREATE INDEX ix_pipeline_customer       ON uk_ecommerce_pipeline (Customer_UUID, Transaction_Timestamp);
CREATE INDEX ix_pipeline_timestamp      ON uk_ecommerce_pipeline (Transaction_Timestamp);


-- @block: transform
/* Staging to governed table with explicit casting. Any row that violates a
   CHECK aborts the load, so bad data cannot reach Power BI silently. */
INSERT INTO uk_ecommerce_pipeline (
    Transaction_ID, Transaction_Timestamp, Customer_UUID, Revenue_Amount_GBP,
    Deal_Stage, Channel, Region, Product_Category, Response_Time_Hours,
    Interaction_Note, Friction_Reason, Stage_Inferred, Is_Closed_Lost, Leakage_GBP
)
SELECT
    TRIM(UPPER(Transaction_ID)),
    datetime(TRIM(Transaction_Timestamp)),
    TRIM(LOWER(Customer_UUID)),
    ROUND(CAST(TRIM(Revenue_Amount_GBP) AS REAL), 2),
    TRIM(Deal_Stage),
    COALESCE(NULLIF(TRIM(Channel), ''), 'Unknown'),
    COALESCE(NULLIF(TRIM(Region), ''), 'Unknown'),
    COALESCE(NULLIF(TRIM(Product_Category), ''), 'Unknown'),
    CAST(CAST(NULLIF(TRIM(Response_Time_Hours), '') AS REAL) AS INTEGER),
    NULLIF(TRIM(Interaction_Note), ''),
    NULLIF(NULLIF(TRIM(Friction_Reason), ''), 'None'),
    CASE WHEN LOWER(TRIM(Stage_Inferred)) IN ('true','1')  THEN 1 ELSE 0 END,
    CASE WHEN LOWER(TRIM(Is_Closed_Lost)) IN ('true','1')  THEN 1 ELSE 0 END,
    ROUND(CAST(TRIM(Leakage_GBP) AS REAL), 2)
FROM stg_crm_migration;


-- @query: 1_revenue_leakage_audit
/* Closed-Lost revenue and deal counts by operational friction driver.
   The three named drivers are explicit; anything else is bucketed so the
   total always reconciles to the full Closed-Lost book. */
WITH lost AS (
    SELECT
        CASE
            WHEN Friction_Reason = 'Response Delay'      THEN 'Response Delay'
            WHEN Friction_Reason = 'Warehouse Stockout'  THEN 'Warehouse Stockout'
            WHEN Friction_Reason = 'Navigation Friction' THEN 'Navigation Friction'
            ELSE 'Unattributed'
        END                                          AS Friction_Driver,
        Revenue_Amount_GBP,
        Response_Time_Hours
    FROM uk_ecommerce_pipeline
    WHERE Deal_Stage = 'Closed-Lost'
)
SELECT
    Friction_Driver,
    COUNT(*)                                                         AS Closed_Lost_Deals,
    ROUND(SUM(Revenue_Amount_GBP), 2)                                AS Closed_Lost_Revenue_GBP,
    ROUND(AVG(Revenue_Amount_GBP), 2)                                AS Avg_Lost_Deal_GBP,
    ROUND(100.0 * SUM(Revenue_Amount_GBP)
          / SUM(SUM(Revenue_Amount_GBP)) OVER (), 1)                 AS Share_Of_Leakage_Pct,
    ROUND(AVG(CASE WHEN Friction_Driver = 'Response Delay'
                   THEN Response_Time_Hours END), 1)                 AS Avg_Response_Hours
FROM lost
GROUP BY Friction_Driver
ORDER BY
    CASE Friction_Driver
        WHEN 'Response Delay'      THEN 1
        WHEN 'Warehouse Stockout'  THEN 2
        WHEN 'Navigation Friction' THEN 3
        ELSE 4
    END;


-- @query: 2_active_forecasting_pipeline
/* Expected revenue from Open deals, weighted by stage win probability and
   discounted when the deal already shows friction (the same signals that
   drive historic Closed-Lost leakage). Closed deals anchor the forecast. */
WITH stage_probability (Deal_Stage, Base_Probability) AS (
    VALUES ('Closed-Won', 1.00),
           ('Open',       0.40),
           ('Closed-Lost', 0.00)
),
friction_penalty (Friction_Reason, Probability_Multiplier) AS (
    VALUES ('Response Delay',      0.50),
           ('Warehouse Stockout',  0.40),
           ('Navigation Friction', 0.60)
),
scored AS (
    SELECT
        strftime('%Y-%m', p.Transaction_Timestamp)                 AS Pipeline_Month,
        p.Deal_Stage,
        p.Revenue_Amount_GBP,
        sp.Base_Probability
          * COALESCE(fp.Probability_Multiplier, 1.0)               AS Win_Probability,
        CASE WHEN fp.Friction_Reason IS NOT NULL THEN 1 ELSE 0 END AS At_Risk
    FROM uk_ecommerce_pipeline p
    JOIN stage_probability sp      ON sp.Deal_Stage = p.Deal_Stage
    LEFT JOIN friction_penalty fp  ON fp.Friction_Reason = p.Friction_Reason
                                  AND p.Deal_Stage = 'Open'
)
SELECT
    Pipeline_Month,
    SUM(CASE WHEN Deal_Stage = 'Open' THEN 1 ELSE 0 END)                         AS Open_Deals,
    ROUND(SUM(CASE WHEN Deal_Stage = 'Open' THEN Revenue_Amount_GBP ELSE 0 END), 2)
                                                                                 AS Open_Pipeline_GBP,
    ROUND(SUM(CASE WHEN Deal_Stage = 'Open'
                   THEN Revenue_Amount_GBP * Win_Probability ELSE 0 END), 2)     AS Weighted_Open_GBP,
    SUM(CASE WHEN Deal_Stage = 'Open' AND At_Risk = 1 THEN 1 ELSE 0 END)         AS Open_Deals_At_Risk,
    ROUND(SUM(CASE WHEN Deal_Stage = 'Closed-Won' THEN Revenue_Amount_GBP ELSE 0 END), 2)
                                                                                 AS Booked_Won_GBP,
    ROUND(SUM(Revenue_Amount_GBP * Win_Probability), 2)                          AS Expected_Total_GBP
FROM scored
GROUP BY Pipeline_Month
ORDER BY Pipeline_Month;


-- @query: 3a_data_hygiene_scorecard
/* One row per hygiene rule: how many records fail, and what share. */
WITH base AS (SELECT COUNT(*) AS n FROM uk_ecommerce_pipeline),
checks AS (
    SELECT 'Duplicate Transaction_ID' AS Hygiene_Check,
           (SELECT COUNT(*) - COUNT(DISTINCT Transaction_ID) FROM uk_ecommerce_pipeline) AS Failing_Rows
    UNION ALL
    SELECT 'Suspected double post (same customer, amount, timestamp)',
           (SELECT COALESCE(SUM(c - 1), 0) FROM (
                SELECT COUNT(*) AS c
                FROM uk_ecommerce_pipeline
                GROUP BY Customer_UUID, Revenue_Amount_GBP, Transaction_Timestamp
                HAVING COUNT(*) > 1))
    UNION ALL
    SELECT 'Suspected duplicate lead (same customer, category, day)',
           (SELECT COALESCE(SUM(c - 1), 0) FROM (
                SELECT COUNT(*) AS c
                FROM uk_ecommerce_pipeline
                GROUP BY Customer_UUID, Product_Category, date(Transaction_Timestamp)
                HAVING COUNT(*) > 1))
    UNION ALL
    SELECT 'Missing channel attribution',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline WHERE Channel = 'Unknown')
    UNION ALL
    SELECT 'Missing region attribution',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline WHERE Region = 'Unknown')
    UNION ALL
    SELECT 'Missing product category',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline WHERE Product_Category = 'Unknown')
    UNION ALL
    SELECT 'Closed-Lost with no friction attribution',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline
            WHERE Deal_Stage = 'Closed-Lost'
              AND (Friction_Reason IS NULL OR Friction_Reason = 'Unattributed'))
    UNION ALL
    SELECT 'Stage inferred, not recorded in CRM',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline WHERE Stage_Inferred = 1)
    UNION ALL
    SELECT 'Missing response time',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline WHERE Response_Time_Hours IS NULL)
    UNION ALL
    SELECT 'Blank interaction note',
           (SELECT COUNT(*) FROM uk_ecommerce_pipeline WHERE Interaction_Note IS NULL)
)
SELECT
    c.Hygiene_Check,
    c.Failing_Rows,
    ROUND(100.0 * c.Failing_Rows / b.n, 2)                     AS Failing_Pct,
    CASE WHEN c.Failing_Rows = 0 THEN 'PASS'
         WHEN 100.0 * c.Failing_Rows / b.n < 2 THEN 'WARN'
         ELSE 'FAIL' END                                       AS Status
FROM checks c CROSS JOIN base b
ORDER BY c.Failing_Rows DESC;


-- @query: 3b_data_hygiene_detail
/* Record level worklist for RevOps: every row breaking lead attribution,
   with the specific reasons concatenated for the CRM owner to fix. */
SELECT
    Transaction_ID,
    Customer_UUID,
    Transaction_Timestamp,
    Deal_Stage,
    Revenue_Amount_GBP,
    TRIM(
        CASE WHEN Channel = 'Unknown'          THEN 'NO_CHANNEL '  ELSE '' END ||
        CASE WHEN Region = 'Unknown'           THEN 'NO_REGION '   ELSE '' END ||
        CASE WHEN Product_Category = 'Unknown' THEN 'NO_CATEGORY ' ELSE '' END ||
        CASE WHEN Deal_Stage = 'Closed-Lost'
              AND (Friction_Reason IS NULL OR Friction_Reason = 'Unattributed')
                                               THEN 'LOST_NO_CAUSE ' ELSE '' END ||
        CASE WHEN Stage_Inferred = 1           THEN 'STAGE_INFERRED ' ELSE '' END ||
        CASE WHEN Response_Time_Hours IS NULL  THEN 'NO_RESPONSE_TIME ' ELSE '' END
    )                                                          AS Hygiene_Flags
FROM uk_ecommerce_pipeline
WHERE Channel = 'Unknown'
   OR Region = 'Unknown'
   OR Product_Category = 'Unknown'
   OR (Deal_Stage = 'Closed-Lost' AND (Friction_Reason IS NULL OR Friction_Reason = 'Unattributed'))
   OR Stage_Inferred = 1
   OR Response_Time_Hours IS NULL
ORDER BY Revenue_Amount_GBP DESC;
BEGIN TRANSACTION;
CREATE TABLE changes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    surface TEXT NOT NULL,
    target TEXT NOT NULL,
    version INTEGER NOT NULL,
    before_text TEXT,
    after_text TEXT,
    diff TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL,
    turn TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    core INTEGER NOT NULL DEFAULT 0,
    core_reasons TEXT NOT NULL DEFAULT '[]',
    gate TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL
, waits TEXT NOT NULL DEFAULT '');
INSERT INTO "changes" VALUES(1,'e33516a8e0a54ba3','parameter','recall.min_score',1,'{"base":0.0,"value":12.0}','{"base":0.0,"value":8.0}','--- recall.min_score (before)
+++ recall.min_score (after)
@@ -1 +1 @@
-{"base":0.0,"value":12.0}+{"base":0.0,"value":8.0}','tuner','','on the practice tasks: +0.652 score, inf% dearer (12.0 -> 8.0, best of 83 moves)','live',0,'[]','{"status": "pass", "checks": [{"name": "hygiene", "status": "pass", "detail": "", "score": null}, {"name": "parameter", "status": "pass", "detail": "a declared parameter within its limits", "score": null}]}','held on 43 new tasks','',1795465242360,1795465242843,'measurement');
INSERT INTO "changes" VALUES(2,'c8e89a99f624406b','parameter','recall.turn_limit',1,NULL,'{"base":6,"value":2}','--- /dev/null
+++ recall.turn_limit (after)
@@ -0,0 +1 @@
+{"base":6,"value":2}','tuner','','on the practice tasks: +0.000 score, 67% cheaper (6 -> 2, best of 87 moves)','blocked',0,'[]','{"status": "pass", "checks": [{"name": "hygiene", "status": "pass", "detail": "", "score": null}, {"name": "parameter", "status": "pass", "detail": "a declared parameter within its limits", "score": null}]}','no clear difference on 63 tasks','',1795465243040,1795465243065,'measurement');
INSERT INTO "changes" VALUES(3,'112c0f55b8944226','parameter','recall.turn_limit',2,NULL,'{"base":6,"value":4}','--- /dev/null
+++ recall.turn_limit (after)
@@ -0,0 +1 @@
+{"base":6,"value":4}','tuner','','on the practice tasks: +0.000 score, 33% cheaper (6 -> 4, best of 86 moves)','blocked',0,'[]','{"status": "pass", "checks": [{"name": "hygiene", "status": "pass", "detail": "", "score": null}, {"name": "parameter", "status": "pass", "detail": "a declared parameter within its limits", "score": null}]}','no clear difference on 63 tasks','',1795465243317,1795465243349,'measurement');
CREATE TABLE evaluations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    suite TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    detail TEXT NOT NULL DEFAULT ''
);
INSERT INTO "evaluations" VALUES(1,'e33516a8e0a54ba3',1795465242369,'hygiene','pass',NULL,'');
INSERT INTO "evaluations" VALUES(2,'e33516a8e0a54ba3',1795465242372,'parameter','pass',NULL,'a declared parameter within its limits');
INSERT INTO "evaluations" VALUES(3,'c8e89a99f624406b',1795465243046,'hygiene','pass',NULL,'');
INSERT INTO "evaluations" VALUES(4,'c8e89a99f624406b',1795465243048,'parameter','pass',NULL,'a declared parameter within its limits');
INSERT INTO "evaluations" VALUES(5,'112c0f55b8944226',1795465243321,'hygiene','pass',NULL,'');
INSERT INTO "evaluations" VALUES(6,'112c0f55b8944226',1795465243324,'parameter','pass',NULL,'a declared parameter within its limits');
CREATE TABLE evidence (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    step TEXT NOT NULL,
    verdict TEXT NOT NULL,
    body TEXT NOT NULL
);
INSERT INTO "evidence" VALUES(1,'e33516a8e0a54ba3',1795465242817,'admit','accept','{"alpha": 0.05, "baseline": "fp_8d38e6835f77ca", "others": [], "reason": "better on 63 tasks", "split": "select", "target": {"cost_diff": 150.0, "diff": 0.5238, "domain": "recall", "high": 0.665, "low": 0.345, "n": 63}, "verdict": "accept"}');
INSERT INTO "evidence" VALUES(2,'e33516a8e0a54ba3',1795465242840,'settle','accept','{"alpha": 0.0, "baseline": "", "others": [], "reason": "held on 43 new tasks", "split": "guard", "target": {"cost_diff": 150.0, "diff": 0.5814, "domain": "recall", "high": 0.805, "low": 0.36, "n": 43}, "verdict": "accept"}');
INSERT INTO "evidence" VALUES(3,'c8e89a99f624406b',1795465243063,'decline','reject','{"alpha": 0.05, "baseline": "fp_b5dc8181dd1f49", "others": [], "reason": "no clear difference on 63 tasks", "split": "select", "target": {"cost_diff": -100.0, "diff": 0.0, "domain": "recall", "high": 0.09, "low": -0.09, "n": 63}, "verdict": "reject"}');
INSERT INTO "evidence" VALUES(4,'e33516a8e0a54ba3',1795465243086,'settle','accept','{"alpha": 0.0, "baseline": "", "others": [], "reason": "held on 43 new tasks", "split": "guard", "target": {"cost_diff": 150.0, "diff": 0.5814, "domain": "recall", "high": 0.805, "low": 0.36, "n": 43}, "verdict": "accept"}');
INSERT INTO "evidence" VALUES(5,'112c0f55b8944226',1795465243343,'decline','reject','{"alpha": 0.05, "baseline": "fp_b5dc8181dd1f49", "others": [], "reason": "no clear difference on 63 tasks", "split": "select", "target": {"cost_diff": -50.0, "diff": 0.0, "domain": "recall", "high": 0.09, "low": -0.09, "n": 63}, "verdict": "reject"}');
CREATE TABLE history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
INSERT INTO "history" VALUES(1,'e33516a8e0a54ba3',1795465242360,'','proposed','tuner','recorded');
INSERT INTO "history" VALUES(2,'e33516a8e0a54ba3',1795465242820,'proposed','trial','gate','better on 63 tasks');
INSERT INTO "history" VALUES(3,'e33516a8e0a54ba3',1795465242843,'trial','live','gate','held on 43 new tasks');
INSERT INTO "history" VALUES(4,'c8e89a99f624406b',1795465243040,'','proposed','tuner','recorded');
INSERT INTO "history" VALUES(5,'c8e89a99f624406b',1795465243065,'proposed','blocked','gate','no clear difference on 63 tasks');
INSERT INTO "history" VALUES(6,'112c0f55b8944226',1795465243317,'','proposed','tuner','recorded');
INSERT INTO "history" VALUES(7,'112c0f55b8944226',1795465243349,'proposed','blocked','gate','no clear difference on 63 tasks');
CREATE INDEX changes_target ON changes(surface, target);
CREATE INDEX changes_ref ON changes(ref);
CREATE TRIGGER history_no_update BEFORE UPDATE ON history
BEGIN SELECT RAISE(ABORT, 'the self-change history is append-only'); END;
CREATE TRIGGER history_no_delete BEFORE DELETE ON history
BEGIN SELECT RAISE(ABORT, 'the self-change history is append-only'); END;
CREATE TRIGGER evaluations_no_update BEFORE UPDATE ON evaluations
BEGIN SELECT RAISE(ABORT, 'evaluation results are append-only'); END;
CREATE TRIGGER evaluations_no_delete BEFORE DELETE ON evaluations
BEGIN SELECT RAISE(ABORT, 'evaluation results are append-only'); END;
CREATE TRIGGER changes_no_delete BEFORE DELETE ON changes
BEGIN SELECT RAISE(ABORT, 'a recorded self-change is never deleted'); END;
CREATE INDEX evidence_change ON evidence(change_id, seq);
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT, 'measurement evidence is append-only'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'measurement evidence is append-only'); END;
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('changes',3);
INSERT INTO "sqlite_sequence" VALUES('history',7);
INSERT INTO "sqlite_sequence" VALUES('evaluations',6);
INSERT INTO "sqlite_sequence" VALUES('evidence',5);
COMMIT;
PRAGMA user_version = 0;

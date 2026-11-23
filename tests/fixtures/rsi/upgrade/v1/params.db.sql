BEGIN TRANSACTION;
CREATE TABLE params (
            name        TEXT PRIMARY KEY,
            text        TEXT NOT NULL,
            updated_ms  INTEGER NOT NULL
        );
INSERT INTO "params" VALUES('recall.min_score','{"base":0.0,"value":8.0}',1795465242820);
COMMIT;
PRAGMA user_version = 1;

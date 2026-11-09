-- Owner sign-in: one row per signed-in browser. The cookie holds a random token;
-- only its SHA-256 is stored, so a copy of the database can't be used to sign in.

CREATE TABLE owner_sessions (
    token_hash  TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

-- Push subscriptions no longer record who subscribed (there are no accounts).
UPDATE push_subs SET email = NULL;

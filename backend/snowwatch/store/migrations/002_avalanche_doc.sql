-- The normalised avalanche forecast (see snowwatch/avalanche.py), checked against
-- its expiry time on every request.
ALTER TABLE avalanche ADD COLUMN doc_json TEXT;

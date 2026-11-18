-- ETL-owned normalized fingerprint contract v1. Explicit installation only.
-- Install/seed with the writer; consumers SELECT under one source snapshot.
CREATE TABLE IF NOT EXISTS swim_sync_contract(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),version int NOT NULL CHECK(version=1),epoch uuid NOT NULL DEFAULT gen_random_uuid(),seeded boolean NOT NULL DEFAULT false);
INSERT INTO swim_sync_contract(singleton,version) VALUES(true,1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS swim_sync_result(result_id bigint PRIMARY KEY,meet_id int NOT NULL,source_key text NOT NULL UNIQUE,fingerprint text NOT NULL);
CREATE INDEX IF NOT EXISTS swim_sync_result_meet ON swim_sync_result(meet_id,result_id);
CREATE TABLE IF NOT EXISTS swim_sync_dirty(result_id bigint PRIMARY KEY);
CREATE OR REPLACE FUNCTION swim_sync_payload(result_ids bigint[]) RETURNS TABLE(payload jsonb)
LANGUAGE sql STABLE AS $$
WITH split_rows AS (
   SELECT s.result_id,jsonb_agg(jsonb_build_object('distance',s.distance,'time_seconds',s.time_seconds::text,'order',s.split_order) ORDER BY s.split_order,s.distance,s.id) AS splits
   FROM splits s JOIN results r ON r.id=s.result_id WHERE r.id=ANY(result_ids) GROUP BY s.result_id
  ) SELECT jsonb_build_object(
   'source_key',jsonb_build_array('swimrankings-v1',m.meet_id,r.id)::text,
   'source_result_id',r.id,'swimmer_key',s.swimmer_id,'meet_key',m.meet_id,
   'course',coalesce(nullif(e.pool_length,0),nullif(m.pool_length,0)),
   'distance',e.distance,'stroke',e.stroke,'category',e.gender,
   'race_date',r.result_date,'time_hundredths',(r.time_seconds*100)::integer,
   'status',r.status,'is_relay',r.is_relay,'points',r.points_fina,
   'payload',jsonb_build_object('meet',jsonb_build_object('key',m.meet_id,'name',m.name,'city',m.city,'country',m.country_code),
    'date',r.result_date,'time_seconds',r.time_seconds::text,'status',r.status,'points',r.points_fina,'points_rudolph',r.points_rudolph,
    'reaction_time',r.reaction_time,'heat',r.heat,'lane',r.lane,'round',r.event_round,
    'is_relay',r.is_relay,'relay_count',r.relay_count,'splits',coalesce(sp.splits,'[]'::jsonb))
  ) AS payload FROM results r JOIN swimmers s ON s.id=r.swimmer_id
  JOIN meets m ON m.id=r.meet_id JOIN events e ON e.id=r.event_id
  LEFT JOIN split_rows sp ON sp.result_id=r.id
  WHERE r.id=ANY(result_ids) ORDER BY r.id
$$;
CREATE OR REPLACE FUNCTION swim_sync_capture() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND to_jsonb(NEW)=to_jsonb(OLD) THEN RETURN NULL; END IF;
 IF TG_TABLE_NAME='results' THEN
  IF TG_OP<>'INSERT' THEN INSERT INTO swim_sync_dirty VALUES(OLD.id) ON CONFLICT DO NOTHING; END IF;
  IF TG_OP<>'DELETE' THEN INSERT INTO swim_sync_dirty VALUES(NEW.id) ON CONFLICT DO NOTHING; END IF;
 ELSIF TG_TABLE_NAME='splits' THEN
  IF TG_OP<>'INSERT' THEN INSERT INTO swim_sync_dirty VALUES(OLD.result_id) ON CONFLICT DO NOTHING; END IF;
  IF TG_OP<>'DELETE' THEN INSERT INTO swim_sync_dirty VALUES(NEW.result_id) ON CONFLICT DO NOTHING; END IF;
 ELSIF TG_TABLE_NAME='meets' THEN
  INSERT INTO swim_sync_dirty SELECT id FROM results WHERE meet_id=NEW.id ON CONFLICT DO NOTHING;
 ELSIF TG_TABLE_NAME='events' THEN
  INSERT INTO swim_sync_dirty SELECT id FROM results WHERE event_id=NEW.id ON CONFLICT DO NOTHING;
 ELSIF TG_TABLE_NAME='swimmers' AND NEW.swimmer_id IS DISTINCT FROM OLD.swimmer_id THEN
  INSERT INTO swim_sync_dirty SELECT id FROM results WHERE swimmer_id=NEW.id ON CONFLICT DO NOTHING;
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION swim_sync_invalidate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 UPDATE swim_sync_contract SET seeded=false;
 INSERT INTO swim_sync_dirty SELECT result_id FROM swim_sync_result ON CONFLICT DO NOTHING;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION swim_sync_refresh(batch_size int DEFAULT 500) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE ids bigint[]; changed bigint; removed bigint; remaining boolean;
BEGIN
 IF batch_size<1 OR batch_size>5000 THEN RAISE EXCEPTION 'Invalid sync batch size'; END IF;
 PERFORM pg_advisory_xact_lock(734342);
 SELECT array_agg(result_id) INTO ids FROM (SELECT result_id FROM swim_sync_dirty ORDER BY result_id LIMIT batch_size FOR UPDATE SKIP LOCKED) k;
 IF ids IS NOT NULL THEN
  DELETE FROM swim_sync_result s WHERE s.result_id=ANY(ids) AND NOT EXISTS(SELECT 1 FROM results r WHERE r.id=s.result_id);
  GET DIAGNOSTICS removed=ROW_COUNT;
  INSERT INTO swim_sync_result(result_id,meet_id,source_key,fingerprint)
  SELECT (p.payload->>'source_result_id')::bigint,r.meet_id,p.payload->>'source_key',md5(p.payload::text)
  FROM swim_sync_payload(ids) p JOIN results r ON r.id=(p.payload->>'source_result_id')::bigint
  ON CONFLICT(result_id) DO UPDATE SET meet_id=excluded.meet_id,source_key=excluded.source_key,fingerprint=excluded.fingerprint
  WHERE (swim_sync_result.meet_id,swim_sync_result.source_key,swim_sync_result.fingerprint) IS DISTINCT FROM (excluded.meet_id,excluded.source_key,excluded.fingerprint);
  GET DIAGNOSTICS changed=ROW_COUNT;
  -- An incomplete inner join must never certify the projection as current.
  IF EXISTS(SELECT 1 FROM results r WHERE r.id=ANY(ids) AND (NOT EXISTS(SELECT 1 FROM swimmers s WHERE s.id=r.swimmer_id) OR NOT EXISTS(SELECT 1 FROM meets m WHERE m.id=r.meet_id) OR NOT EXISTS(SELECT 1 FROM events e WHERE e.id=r.event_id))) THEN RAISE EXCEPTION 'Incomplete sync source dependencies'; END IF;
  DELETE FROM swim_sync_dirty WHERE result_id=ANY(ids);
 END IF;
 SELECT EXISTS(SELECT 1 FROM swim_sync_dirty) INTO remaining;
 IF NOT remaining THEN UPDATE swim_sync_contract SET seeded=true WHERE NOT seeded; END IF;
 RETURN jsonb_build_object('processed',coalesce(cardinality(ids),0),'changed',coalesce(changed,0),'removed',coalesce(removed,0),'pending',remaining);
END $$;
DO $$ DECLARE t text; f text; BEGIN
 FOREACH t IN ARRAY ARRAY['results','splits','meets','events','swimmers'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS swim_sync_capture ON %I',t);
  EXECUTE format('CREATE TRIGGER swim_sync_capture AFTER %s ON %I FOR EACH ROW EXECUTE FUNCTION swim_sync_capture()',CASE WHEN t IN ('results','splits') THEN 'INSERT OR UPDATE OR DELETE' ELSE 'UPDATE' END,t);
  EXECUTE format('DROP TRIGGER IF EXISTS swim_sync_invalidate ON %I',t);
  EXECUTE format('CREATE TRIGGER swim_sync_invalidate AFTER TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION swim_sync_invalidate()',t);
 END LOOP;
 FOREACH f IN ARRAY ARRAY['swim_sync_payload(bigint[])','swim_sync_capture()','swim_sync_invalidate()','swim_sync_refresh(integer)'] LOOP
  EXECUTE format('ALTER FUNCTION %s SET search_path TO %I,pg_temp',f,current_schema());
 END LOOP;
END $$;
REVOKE ALL ON swim_sync_contract,swim_sync_result,swim_sync_dirty FROM PUBLIC;
REVOKE ALL ON FUNCTION swim_sync_refresh(integer) FROM PUBLIC;
-- Explicit rebuild/initialization: queue facts and retained rows once, then commit
-- bounded refresh batches. Consumers refuse unseeded or dirty projections.
UPDATE swim_sync_contract SET seeded=false;
INSERT INTO swim_sync_dirty SELECT id FROM results UNION SELECT result_id FROM swim_sync_result ON CONFLICT DO NOTHING;

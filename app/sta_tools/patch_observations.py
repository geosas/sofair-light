import psycopg
import uuid


def patch_observations(csv_buffer, DB_archive):
    BLOCK_SIZE = 4_000_000  # 4 MB
    TMP_TABLE_NAME = 'observations_'+str(uuid.uuid4()).replace('-', '_')
    with psycopg.connect(**DB_archive) as conn:
        with conn.cursor() as cur:

            cur.execute(psycopg.sql.SQL(f"""
                CREATE TEMP TABLE {TMP_TABLE_NAME} AS
                SELECT "ID", "RESULT_JSON"
                FROM "OBSERVATIONS"
                WHERE false;
            """))

            with conn.cursor() as cur:
                cur.execute(
                    'ALTER TABLE "OBSERVATIONS" DISABLE TRIGGER multidatastreams_actualization_update;')
                conn.commit()
                BLOCK_SIZE = 4_000_000  # 4 MB - a good speed/memory trade-off
                with cur.copy(f'COPY {TMP_TABLE_NAME} ("ID","RESULT_JSON") FROM STDIN WITH CSV HEADER') as copy:
                    while chunk := csv_buffer.read(BLOCK_SIZE):
                        copy.write(chunk)

                print("update data...")
                cur.execute(f"""
                    UPDATE "OBSERVATIONS" AS target
                    SET
                        "RESULT_JSON" = tmp."RESULT_JSON"
                    FROM {TMP_TABLE_NAME} AS tmp
                    WHERE target."ID" = tmp."ID";
                """)
                cur.execute(
                    'ALTER TABLE "OBSERVATIONS" ENABLE TRIGGER multidatastreams_actualization_update;')
                conn.commit()
        conn.commit()
    print("Update completed successfully.")
    return True

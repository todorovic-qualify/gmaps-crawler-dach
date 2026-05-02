export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { prisma } = await import("./lib/prisma");
    try {
      await prisma.$executeRawUnsafe(`
        CREATE TABLE IF NOT EXISTS "dach_job" (
          "id"             TEXT NOT NULL,
          "ort"            TEXT NOT NULL DEFAULT '',
          "status"         TEXT NOT NULL DEFAULT 'laeuft',
          "gefiltert"      INTEGER NOT NULL DEFAULT 0,
          "verarbeitet"    INTEGER NOT NULL DEFAULT 0,
          "fehler"         TEXT,
          "erstellt_am"    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
          "aktualisiert_am" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT "dach_job_pkey" PRIMARY KEY ("id")
        );
      `);
      await prisma.$executeRawUnsafe(`
        CREATE TABLE IF NOT EXISTS "dach_lead" (
          "id"                   TEXT NOT NULL,
          "job_id"               TEXT NOT NULL,
          "osm_id"               TEXT NOT NULL,
          "name"                 TEXT,
          "operator"             TEXT,
          "brand"                TEXT,
          "gebaeude_typ"         TEXT,
          "gebaeude_nutzung"     TEXT,
          "dachflaeche_qm"       DOUBLE PRECISION NOT NULL DEFAULT 0,
          "adresse"              TEXT,
          "postleitzahl"         TEXT,
          "stadt"                TEXT,
          "telefon"              TEXT,
          "email"                TEXT,
          "alle_emails"          TEXT,
          "alle_telefone"        TEXT,
          "webseite"             TEXT,
          "entscheidungstraeger" TEXT,
          "rechtlicher_name"     TEXT,
          "impressum_info"       TEXT,
          "quelle_url"           TEXT,
          "google_maps_url"      TEXT,
          "kontakt_vorhanden"    BOOLEAN NOT NULL DEFAULT false,
          "hat_pv_anlage"        TEXT,
          "lat"                  DOUBLE PRECISION,
          "lon"                  DOUBLE PRECISION,
          "erstellt_am"          TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
          CONSTRAINT "dach_lead_pkey" PRIMARY KEY ("id")
        );
      `);
      await prisma.$executeRawUnsafe(`
        CREATE UNIQUE INDEX IF NOT EXISTS "dach_lead_job_id_osm_id_key"
          ON "dach_lead"("job_id", "osm_id");
      `);
      await prisma.$executeRawUnsafe(`
        CREATE INDEX IF NOT EXISTS "dach_lead_job_id_idx"
          ON "dach_lead"("job_id");
      `);
      await prisma.$executeRawUnsafe(`
        DO $$ BEGIN
          ALTER TABLE "dach_lead"
            ADD CONSTRAINT "dach_lead_job_id_fkey"
            FOREIGN KEY ("job_id") REFERENCES "dach_job"("id")
            ON DELETE CASCADE ON UPDATE CASCADE;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
      `);
    } catch {
      // Tabellen existieren bereits oder DB nicht erreichbar – kein Problem
    }
  }
}

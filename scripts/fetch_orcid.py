from pathlib import Path

import requests
import yaml


ORCID_ID = "0000-0002-7470-177X"

ORCID_URL = (
    f"https://pub.orcid.org/v3.0/{ORCID_ID}/works"
    "?rows=200"
)

PUBMED_SEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)


HEADERS = {
    "Accept": "application/json"
}


# --------------------------------------------------
# ORCID
# --------------------------------------------------

response = requests.get(
    ORCID_URL,
    headers=HEADERS,
    timeout=30
)

response.raise_for_status()

data = response.json()

publications = []


for group in data.get("group", []):

    summaries = group.get("work-summary", [])

    if not summaries:
        continue

    work = summaries[0]

    title = (
        work.get("title", {})
        .get("title", {})
        .get("value", "")
        .strip()
    )

    year = ""

    publication_date = work.get("publication-date")

    if publication_date:
        year = (
            publication_date
            .get("year", {})
            .get("value", "")
        )

    journal = ""

    if work.get("journal-title"):
        journal = (
            work["journal-title"]
            .get("value", "")
            .strip()
        )


    # --------------------------------------------------
    # DOI z ORCID
    # --------------------------------------------------

    doi = ""

    external_ids = (
        work.get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:

        id_type = (
            external_id
            .get("external-id-type", "")
            .lower()
        )

        if id_type == "doi":

            doi = (
                external_id
                .get("external-id-value", "")
                .strip()
            )

            break


    # --------------------------------------------------
    # PMID z ORCID, pokud existuje
    # --------------------------------------------------

    pmid = ""

    for external_id in external_ids:

        id_type = (
            external_id
            .get("external-id-type", "")
            .lower()
        )

        if id_type in ("pmid", "pubmed"):

            pmid = (
                external_id
                .get("external-id-value", "")
                .strip()
            )

            break


    publications.append(
        {
            "year": year,
            "title": title,
            "journal": journal,
            "doi": doi,
            "pmid": pmid
        }
    )


# --------------------------------------------------
# Pokud ORCID nemá PMID, najdeme ho podle DOI
# --------------------------------------------------

for publication in publications:

    if publication["pmid"]:
        continue

    doi = publication["doi"]

    if not doi:
        continue

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1
    }

    try:

        response = requests.get(
            PUBMED_SEARCH_URL,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        ids = (
            result
            .get("esearchresult", {})
            .get("idlist", [])
        )

        if ids:
            publication["pmid"] = ids[0]

    except requests.RequestException as error:

        print(
            f"PubMed lookup failed for DOI "
            f"{doi}: {error}"
        )


# --------------------------------------------------
# Odstranění duplicit
# --------------------------------------------------

unique = {}

for publication in publications:

    doi = publication["doi"]

    if doi:
        key = doi.lower()
    else:
        key = publication["title"].lower()

    unique[key] = publication


publications = list(unique.values())


# --------------------------------------------------
# Řazení podle roku
# --------------------------------------------------

publications.sort(
    key=lambda x: int(x["year"])
    if x["year"] else 0,
    reverse=True
)


# --------------------------------------------------
# Uložení YAML
# --------------------------------------------------

base_dir = Path(__file__).resolve().parent.parent

output = base_dir / "_data" / "publications.yml"

with open(
    output,
    "w",
    encoding="utf-8"
) as file:

    yaml.dump(
        publications,
        file,
        allow_unicode=True,
        sort_keys=False
    )


print(
    f"Updated {len(publications)} publications"
)

print(f"Saved to: {output}")

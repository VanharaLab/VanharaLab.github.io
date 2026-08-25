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

CROSSREF_URL = "https://api.crossref.org/works/"


HEADERS = {
    "Accept": "application/json"
}


def get_orcid_works():
    response = requests.get(
        ORCID_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def get_doi(work):
    external_ids = (
        work.get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:
        if (
            external_id
            .get("external-id-type", "")
            .lower()
            == "doi"
        ):
            return (
                external_id
                .get("external-id-value", "")
                .strip()
            )

    return ""


def get_pmid_from_pubmed(doi):
    if not doi:
        return ""

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1
    }

    response = requests.get(
        PUBMED_SEARCH_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    ids = (
        response.json()
        .get("esearchresult", {})
        .get("idlist", [])
    )

    return ids[0] if ids else ""


def get_crossref_metadata(doi):
    if not doi:
        return {}

    url = CROSSREF_URL + doi

    response = requests.get(
        url,
        timeout=30
    )

    if response.status_code != 200:
        print(
            f"Crossref lookup failed for DOI: {doi}"
        )
        return {}

    return response.json().get("message", {})


def format_authors(metadata):
    authors = []

    for author in metadata.get("author", []):
        family = author.get("family", "")
        given = author.get("given", "")

        if not family:
            continue

        # Initials from given name
        initials = ""

        for part in given.replace("-", " ").split():
            if part:
                initials += part[0].upper()

        if initials:
            authors.append(
                f"{family} {initials}"
            )
        else:
            authors.append(family)

    return ", ".join(authors)


data = get_orcid_works()

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

    doi = get_doi(work)

    # --------------------------------------------------
    # Crossref metadata
    # --------------------------------------------------

    metadata = get_crossref_metadata(doi)

    journal = ""

    if metadata.get("container-title"):
        journal = metadata["container-title"][0]

    volume = metadata.get("volume", "")
    issue = metadata.get("issue", "")

    pages = (
        metadata.get("page")
        or metadata.get("article-number")
        or ""
    )

    authors = format_authors(metadata)

    # --------------------------------------------------
    # Pokud Crossref nemá název, použijeme ORCID
    # --------------------------------------------------

    if metadata.get("title"):
        crossref_title = metadata["title"][0]

        if crossref_title:
            title = crossref_title

    # --------------------------------------------------
    # PMID
    # --------------------------------------------------

    pmid = get_pmid_from_pubmed(doi)

    publication = {
        "year": year,
        "title": title,
        "authors": authors,
        "journal": journal,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
        "pmid": pmid
    }

    publications.append(publication)

    print(
        f"{year} | {title} | DOI: {doi} | PMID: {pmid}"
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
# Řazení
# --------------------------------------------------

publications.sort(
    key=lambda x: int(x["year"])
    if x["year"]
    else 0,
    reverse=True
)


# --------------------------------------------------
# Uložení
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


print()
print(f"Updated {len(publications)} publications")
print(f"Saved to: {output}")

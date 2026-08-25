from pathlib import Path

import requests
import yaml
import xml.etree.ElementTree as ET


ORCID_ID = "0000-0002-7470-177X"

ORCID_URL = (
    f"https://pub.orcid.org/v3.0/{ORCID_ID}/works"
    "?rows=200"
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

HEADERS = {
    "Accept": "application/json"
}


# --------------------------------------------------
# ORCID
# --------------------------------------------------

print("Fetching publications from ORCID...")

response = requests.get(
    ORCID_URL,
    headers=HEADERS,
    timeout=30
)

response.raise_for_status()

data = response.json()

orcid_publications = []

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

    doi = ""

    external_ids = (
        work.get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:

        if (
            external_id.get("external-id-type", "").lower()
            == "doi"
        ):
            doi = (
                external_id
                .get("external-id-value", "")
                .strip()
            )
            break

    orcid_publications.append(
        {
            "title": title,
            "year": year,
            "journal": journal,
            "doi": doi
        }
    )


print(
    f"ORCID works found: {len(orcid_publications)}"
)


# --------------------------------------------------
# PubMed
# --------------------------------------------------

publications = []

for item in orcid_publications:

    doi = item["doi"]

    # Publikace bez DOI ponecháme.
    if not doi:

        print(
            f"WARNING: no DOI: {item['title']}"
        )

        publications.append(
            {
                "year": item["year"],
                "title": item["title"],
                "authors": "",
                "journal": item["journal"],
                "volume": "",
                "issue": "",
                "pages": "",
                "doi": "",
                "pmid": ""
            }
        )

        continue


    print(f"Looking up DOI: {doi}")


    # --------------------------------------------------
    # Najít PMID podle DOI
    # --------------------------------------------------

    search_params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1
    }

    response = requests.get(
        PUBMED_ESEARCH_URL,
        params=search_params,
        timeout=30
    )

    response.raise_for_status()

    pmids = (
        response.json()
        .get("esearchresult", {})
        .get("idlist", [])
    )


    # --------------------------------------------------
    # DOI není v PubMedu
    # --------------------------------------------------

    if not pmids:

        print(
            f"  PMID not found: {doi}"
        )

        publications.append(
            {
                "year": item["year"],
                "title": item["title"],
                "authors": "",
                "journal": item["journal"],
                "volume": "",
                "issue": "",
                "pages": "",
                "doi": doi,
                "pmid": ""
            }
        )

        continue


    pmid = pmids[0]


    # --------------------------------------------------
    # Stáhnout PubMed XML
    # --------------------------------------------------

    fetch_params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml"
    }

    response = requests.get(
        PUBMED_EFETCH_URL,
        params=fetch_params,
        timeout=30
    )

    response.raise_for_status()

    root = ET.fromstring(response.text)

    article = root.find(".//PubmedArticle")

    if article is None:

        print(
            f"  WARNING: PubMed article not found: {pmid}"
        )

        continue


    art = article.find(".//Article")

    if art is None:
        continue


    # --------------------------------------------------
    # Title
    # --------------------------------------------------

    title = art.findtext(
        "ArticleTitle",
        default=item["title"]
    )


    # --------------------------------------------------
    # Journal
    # --------------------------------------------------

    journal = art.findtext(
        ".//Journal/Title",
        default=item["journal"]
    )


    # --------------------------------------------------
    # Year
    # --------------------------------------------------

    year = art.findtext(
        ".//PubDate/Year",
        default=item["year"]
    )


    # --------------------------------------------------
    # Volume
    # --------------------------------------------------

    volume = art.findtext(
        ".//JournalIssue/Volume",
        default=""
    )


    # --------------------------------------------------
    # Issue
    # --------------------------------------------------

    issue = art.findtext(
        ".//JournalIssue/Issue",
        default=""
    )


    # --------------------------------------------------
    # Pages
    # --------------------------------------------------

    pages = art.findtext(
        ".//Pagination/MedlinePgn",
        default=""
    )


    # --------------------------------------------------
    # Authors
    # --------------------------------------------------

    authors = []

    for author in art.findall(".//Author"):

        lastname = author.findtext("LastName")
        initials = author.findtext("Initials")

        if lastname:

            name = lastname

            if initials:
                name += f" {initials}"

            authors.append(name)


    # --------------------------------------------------
    # PMID
    # --------------------------------------------------

    pubmed_id = article.findtext(
        ".//PMID",
        default=pmid
    )


    publications.append(
        {
            "year": year,
            "title": title,
            "authors": ", ".join(authors),
            "journal": journal,
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "doi": doi,
            "pmid": pubmed_id
        }
    )


    print(
        f"  OK: {title}"
    )


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
print(
    f"Saved {len(publications)} publications"
)
print(
    f"Output: {output}"
)

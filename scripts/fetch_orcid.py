from pathlib import Path
import time

import requests
import yaml
import xml.etree.ElementTree as ET


ORCID_ID = "0000-0002-7470-177X"

ORCID_URL = (
    f"https://pub.orcid.org/v3.0/{ORCID_ID}/works"
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

CROSSREF_URL = "https://api.crossref.org/works/"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VanharaLab-publications/1.0"
}


# --------------------------------------------------
# HTTP session
# --------------------------------------------------

session = requests.Session()
session.headers.update(HEADERS)


# --------------------------------------------------
# ORCID
# Načíst VŠECHNY práce pomocí stránkování
# --------------------------------------------------

def get_orcid_works():

    print("Fetching publications from ORCID...")

    all_groups = []

    start = 0
    rows = 50

    while True:

        params = {
            "start": start,
            "rows": rows
        }

        response = session.get(
            ORCID_URL,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        groups = data.get("group", [])

        if not groups:
            break

        all_groups.extend(groups)

        print(
            f"ORCID: loaded {len(all_groups)} records"
        )

        if len(groups) < rows:
            break

        start += rows

    print(
        f"ORCID total: {len(all_groups)} records"
    )

    return all_groups


# --------------------------------------------------
# DOI z ORCID
# --------------------------------------------------

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


# --------------------------------------------------
# PubMed podle DOI
# --------------------------------------------------

def get_pmid_from_pubmed(doi):

    if not doi:
        return ""

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1
    }

    try:

        response = session.get(
            PUBMED_ESEARCH_URL,
            params=params,
            timeout=30
        )

        if response.status_code == 429:

            print("PubMed rate limit - waiting...")
            time.sleep(3)

            response = session.get(
                PUBMED_ESEARCH_URL,
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

    except requests.RequestException as error:

        print(
            f"WARNING: PubMed search failed for {doi}: {error}"
        )

        return ""


# --------------------------------------------------
# PubMed metadata
# --------------------------------------------------

def get_pubmed_metadata(pmid):

    if not pmid:
        return {}

    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml"
    }

    try:

        response = session.get(
            PUBMED_EFETCH_URL,
            params=params,
            timeout=30
        )

        if response.status_code == 429:

            print(
                f"PubMed rate limit for PMID {pmid} - waiting..."
            )

            time.sleep(3)

            response = session.get(
                PUBMED_EFETCH_URL,
                params=params,
                timeout=30
            )

        response.raise_for_status()

        root = ET.fromstring(response.text)

        article = root.find(".//PubmedArticle")

        if article is None:
            return {}

        art = article.find(".//Article")

        if art is None:
            return {}

        title = art.findtext(
            "ArticleTitle",
            default=""
        )

        journal = art.findtext(
            ".//Journal/Title",
            default=""
        )

        year = art.findtext(
            ".//PubDate/Year",
            default=""
        )

        volume = art.findtext(
            ".//JournalIssue/Volume",
            default=""
        )

        issue = art.findtext(
            ".//JournalIssue/Issue",
            default=""
        )

        pages = art.findtext(
            ".//Pagination/MedlinePgn",
            default=""
        )

        authors = []

        for author in art.findall(".//Author"):

            lastname = author.findtext("LastName")
            initials = author.findtext("Initials")

            if lastname:

                name = lastname

                if initials:
                    name += f" {initials}"

                authors.append(name)

        return {
            "title": title,
            "journal": journal,
            "year": year,
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "authors": ", ".join(authors)
        }

    except requests.RequestException as error:

        print(
            f"WARNING: PubMed fetch failed for PMID {pmid}: {error}"
        )

        return {}

    except ET.ParseError as error:

        print(
            f"WARNING: XML parsing failed for PMID {pmid}: {error}"
        )

        return {}


# --------------------------------------------------
# Crossref
# --------------------------------------------------

def get_crossref_metadata(doi):

    if not doi:
        return {}

    try:

        response = session.get(
            CROSSREF_URL + doi,
            timeout=30
        )

        if response.status_code != 200:

            print(
                f"WARNING: Crossref failed for DOI {doi}"
            )

            return {}

        return response.json().get(
            "message",
            {}
        )

    except requests.RequestException as error:

        print(
            f"WARNING: Crossref request failed for {doi}: {error}"
        )

        return {}


# --------------------------------------------------
# Autoři z Crossref
# --------------------------------------------------

def format_crossref_authors(metadata):

    authors = []

    for author in metadata.get("author", []):

        family = author.get(
            "family",
            ""
        )

        given = author.get(
            "given",
            ""
        )

        if not family:
            continue

        initials = ""

        for part in given.replace(
            "-",
            " "
        ).split():

            if part:
                initials += part[0].upper()

        if initials:
            authors.append(
                f"{family} {initials}"
            )
        else:
            authors.append(family)

    return ", ".join(authors)


# --------------------------------------------------
# ORCID metadata
# --------------------------------------------------

def get_orcid_metadata(work):

    title = (
        work.get("title", {})
        .get("title", {})
        .get("value", "")
        .strip()
    )

    year = ""

    publication_date = work.get(
        "publication-date"
    )

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

    doi = get_doi(work)

    return {
        "title": title,
        "year": year,
        "journal": journal,
        "doi": doi
    }


# --------------------------------------------------
# MAIN
# --------------------------------------------------

groups = get_orcid_works()

publications = []


for index, group in enumerate(groups, start=1):

    summaries = group.get(
        "work-summary",
        []
    )

    if not summaries:
        continue

    work = summaries[0]

    item = get_orcid_metadata(work)

    print()
    print(
        f"[{index}/{len(groups)}] {item['title']}"
    )

    print(
        f"  DOI: {item['doi'] or 'none'}"
    )

    # --------------------------------------------------
    # Výchozí data z ORCID
    # --------------------------------------------------

    publication = {
        "year": item["year"],
        "title": item["title"],
        "authors": "",
        "journal": item["journal"],
        "volume": "",
        "issue": "",
        "pages": "",
        "doi": item["doi"],
        "pmid": ""
    }

    # --------------------------------------------------
    # Crossref
    # --------------------------------------------------

    if item["doi"]:

        metadata = get_crossref_metadata(
            item["doi"]
        )

        if metadata:

            if metadata.get("title"):

                publication["title"] = (
                    metadata["title"][0]
                )

            if metadata.get(
                "container-title"
            ):

                publication["journal"] = (
                    metadata["container-title"][0]
                )

            publication["volume"] = (
                metadata.get("volume", "")
            )

            publication["issue"] = (
                metadata.get("issue", "")
            )

            publication["pages"] = (
                metadata.get("page")
                or metadata.get("article-number")
                or ""
            )

            publication["authors"] = (
                format_crossref_authors(
                    metadata
                )
            )

    # --------------------------------------------------
    # PubMed
    # --------------------------------------------------

    pmid = get_pmid_from_pubmed(
        item["doi"]
    )

    if pmid:

        publication["pmid"] = pmid

        pubmed = get_pubmed_metadata(
            pmid
        )

        if pubmed:

            # PubMed použijeme pro autory
            # a bibliografické údaje.

            if pubmed.get("authors"):
                publication["authors"] = (
                    pubmed["authors"]
                )

            if pubmed.get("journal"):
                publication["journal"] = (
                    pubmed["journal"]
                )

            if pubmed.get("volume"):
                publication["volume"] = (
                    pubmed["volume"]
                )

            if pubmed.get("issue"):
                publication["issue"] = (
                    pubmed["issue"]
                )

            if pubmed.get("pages"):
                publication["pages"] = (
                    pubmed["pages"]
                )

            # DOI a název ponecháme z ORCID/Crossref,
            # aby nedocházelo k chybným DOI.

    print(
        f"  PMID: {publication['pmid'] or 'none'}"
    )

    publications.append(
        publication
    )


# --------------------------------------------------
# Odstranění duplicit
# --------------------------------------------------

unique = {}

for publication in publications:

    doi = publication["doi"].strip()

    if doi:

        key = doi.lower()

    else:

        key = (
            publication["title"]
            .strip()
            .lower()
        )

    if key:
        unique[key] = publication


publications = list(
    unique.values()
)


# --------------------------------------------------
# Řazení
# --------------------------------------------------

def year_key(publication):

    try:
        return int(
            publication["year"]
        )

    except (
        ValueError,
        TypeError
    ):
        return 0


publications.sort(
    key=year_key,
    reverse=True
)


# --------------------------------------------------
# Uložení
# --------------------------------------------------

base_dir = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

output = (
    base_dir
    / "_data"
    / "publications.yml"
)


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


# --------------------------------------------------
# Kontrola
# --------------------------------------------------

print()
print("=" * 60)
print(
    f"ORCID records: {len(groups)}"
)
print(
    f"Publications saved: {len(publications)}"
)
print(
    f"Output: {output}"
)
print("=" * 60)

---
layout: page
title: List of publications
---

{% assign current_year = "" %}

{% for pub in site.data.publications %}

{% if pub.year != current_year %}

## {{ pub.year }}

{% assign current_year = pub.year %}

{% endif %}

- {{ pub.authors }}.  
  **{{ pub.title }}**.  
  *{{ pub.journal }}*.{% if pub.volume %} {{ pub.year }};{{ pub.volume }}{% if pub.issue %}({{ pub.issue }}){% endif %}{% if pub.pages %}:{{ pub.pages }}{% endif %}.{% endif %}
  {% if pub.doi %}[DOI](https://doi.org/{{ pub.doi }}).{% endif %}
  {% if pub.pmid %}[PubMed](https://pubmed.ncbi.nlm.nih.gov/{{ pub.pmid }}/).{% endif %}

{% endfor %}

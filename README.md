# Vinted hunter — drewniane zabawki 0-3

GitHub Actions co godzinę pobiera nowe oferty z Vinted.pl i commituje JSON do repo.
Claude w rozmowie czyta `data/latest.json`, filtruje, ocenia perełki, tworzy draft maila.

## Setup

1. Utwórz prywatne repo, wgraj zawartość tego folderu.
2. Settings → Actions → General → Workflow permissions → Read and write.
3. Actions → Vinted scrape → Run workflow.
4. Po ~1 min w `data/latest.json` są oferty.

## Użycie

W rozmowie z Claude:
> "Repo: github.com/<user>/<repo>. Sprawdź latest.json, wybierz perełki z ostatnich 12h,
> przygotuj mail na klaudiagora89011@gmail.com"

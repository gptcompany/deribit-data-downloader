<!-- gbg-agents:pillars BEGIN sha256=f579c462a229c53881779f8ad6e633d910207064cf777c61892a9994bf03601e -->
## Pilastri nautilus_dev

Fonte: `gbg-agents/instructions/PILLARS.md`; non modificare a mano.

**Filosofia**: segnali adattivi, sicurezza fissa. La gabbia la creiamo noi, non il sistema; i limiti di sicurezza proteggono dalla rovina.

- **P1 Probabilistico**: distribuzioni, non previsioni; risultato riportato qualunque esso sia.
- **P2 Non lineare**: leggi di potenza, non scala lineare (Giller, Mandelbrot); non linearità e code si misurano e si documentano, sub-lineare è il default.
- **P3 Non parametrico**: si adatta ai dati, nessun parametro scelto a mano; i default dei segnali sono punti di partenza. Finestre, soglie, cadenze, half-life e periodi si ricavano dai dati, in modo dinamico e point-in-time (CEEMDAN `strategies/common/orderflow/ceemdan.py` di nautilus_dev, metodi probabilistici o bayesiani `strategies/common/adaptive_control/particle_portfolio.py`, derivazione da misure). Un numero fisso è ammesso solo come LIMITE di sicurezza, denaro o isolamento delle risorse, con il motivo scritto accanto. Non si propone mai all'operatore una scelta tra numeri: si propone il metodo di derivazione. In review, un parametro a mano che non sia un limite è un MEDIUM.
- **P4 Scalare**: vale a ogni frequenza, asset e condizione di mercato; rapporti invece di valori assoluti, invarianti alla scala.
- **Safety Parameters**: leva, dimensione di posizione, stop loss, perdita giornaliera e kill switch sono limiti rigidi, fissi, mai adattivi; il valore sta nella configurazione della repo con il motivo accanto.
- **Ensemble**: più viste e consenso, mai una sola vista come verità.
- **Black Box**: interfacce pulite e implementazione nascosta, tutto sostituibile, una responsabilità per modulo, componenti comuni estratti; velocità costante: 5 righe complete oggi, non ritoccarne 1 domani.
- **KISS e YAGNI**: niente astrazioni o opzioni non richieste; funzioni di al più 50 righe.
- **Native First**: NO custom indicators, nemmeno nuovi: solo `nautilus_trader.indicators` nativi (Rust); mai reimplementare EMA, RSI e simili.
- **Performance**: operazioni vettoriali o wrangler Rust, mai `df.iterrows()`; algoritmi ricorsivi/online O(1) che si adattano di continuo.

## Indice del sistema

Solo puntatori, nessuna regola; repo `gptcompany/<nome>`, branch di default.

- Topologia: `network-infra/ansible/inventory/hosts.yml`, `monitoring-stack/config/services.yaml` (servizi, owner, dipendenze); incompleta: se manca un dato, dillo.
- Tecnologie: `gbg-agents/mise.toml` (versioni), `gbg-agents/docs/decisions/` (scelte), `gbg-agents/docs/research/reuse-catalog.md` (riuso, OSS).
- Registri: `gbg-agents/docs/findings/rows/`, `gbg-agents/docs/credentials/register.json` (solo nomi), `monitoring-stack/docs/` (runbook).
- Stato vivo: `gh pr list` e `gh run list --repo gptcompany/<nome>`, `orca status --json`; allarmi su tk-mon, se non rispondono chiedi al coordinatore.
<!-- gbg-agents:pillars END -->

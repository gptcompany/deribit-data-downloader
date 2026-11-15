<!-- gbg-agents:pillars BEGIN sha256=998976c2f21ac6f69ac5108c5585dd440773e49b564edc404db7ee6f5f7dfbf3 -->
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
<!-- gbg-agents:pillars END -->

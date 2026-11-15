<!-- gbg-agents:pillars BEGIN sha256=e9beab6b95c67661c335eb359dd027b3be4811107a72d1ee480a36074c82afab -->
## Pilastri nautilus_dev

Fonte unica: `gbg-agents/instructions/PILLARS.md`. Le repo che servono Nautilus ricevono questo blocco con hash; non si modifica a mano.

**Filosofia**: segnali adattivi, sicurezza fissa. La gabbia la creiamo noi, non il sistema; i limiti di sicurezza non sono una gabbia, proteggono dalla rovina.

- **P1 Probabilistico**: distribuzioni di probabilità, non previsioni; risultato riportato qualunque esso sia.
- **P2 Non lineare**: leggi di potenza, non scala lineare (Giller, Mandelbrot); non linearità e code si misurano e si documentano, sub-lineare è il default.
- **P3 Non parametrico**: si adatta ai dati, nessun parametro scelto a mano. Finestre, soglie, cadenze, half-life e periodi si ricavano dai dati, in modo dinamico e point-in-time (CEEMDAN `strategies/common/orderflow/ceemdan.py` di nautilus_dev, metodi probabilistici o bayesiani `strategies/common/adaptive_control/particle_portfolio.py`, derivazione da misure). Un numero fisso è ammesso solo come LIMITE di sicurezza, denaro o isolamento delle risorse, con il motivo scritto accanto. Non si propone mai all'operatore una scelta tra numeri: si propone il metodo di derivazione. In review, un parametro a mano che non sia un limite è un MEDIUM.
- **P4 Scalare**: vale a ogni frequenza, asset e condizione di mercato.
- **Safety Parameters**: leva, dimensione di posizione, stop loss, perdita giornaliera e kill switch sono fissi, mai adattivi; il valore sta nella configurazione della repo con il motivo accanto.
- **Black Box**: moduli con interfacce pulite e implementazione nascosta, tutto sostituibile, una responsabilità per modulo, componenti comuni estratti.
- **KISS e YAGNI**: niente astrazioni o opzioni non richieste; funzioni di al più 50 righe.
- **Native First**: indicatori e strumenti nativi di NautilusTrader (Rust) prima di codice proprio; mai reimplementare EMA, RSI e simili.
- **Performance**: operazioni vettoriali o wrangler Rust, mai `df.iterrows()`; algoritmi ricorsivi/online O(1).
<!-- gbg-agents:pillars END -->

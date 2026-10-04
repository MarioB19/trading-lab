---
fecha: 2026-10-03
tags: [trading-lab, investigación, evidencia, estrategia]
estado: activo
---

# Investigación de estrategias sencillas con capital total de US$1,000

Fecha de consulta: 3-oct-2026, America/Mexico_City. Capital confirmado: US$500 cripto y US$500 ETFs. Investigación de ocho fuentes primarias; ninguna corrida de mercado, optimización, descarga de pago ni cambio de estrategia. Este documento propone familias para declarar posteriormente, no una estrategia validada ni un preregistro aprobado.

**La literatura justifica investigar menor rotación y tendencia lenta, pero no identifica una receta que asegure ganancias en este proyecto.** Los artículos que encuentran momentum usan otros universos, costos y frecuencias, y muchos requieren posiciones cortas. La ventaja comercial aquí debe superar comisiones, fricción ejecutable y hosting con sólo US$1,000. Un método que reduzca caídas puede ser útil sin producir más dinero; esas dos hipótesis deben evaluarse por separado.

## Ocho fuentes y qué permiten concluir

### 1. Momentum temporal: fundamento, con una implementación distinta

Moskowitz, Ooi y Pedersen, **Time Series Momentum**, Journal of Financial Economics, 2012. Estudian 58 futuros/forwards y encuentran persistencia relacionada con el retorno propio de los 12 meses anteriores. Es una justificación para investigar señales temporales sencillas y estabilidad entre activos. Su estrategia diversificada incluye posiciones largas/cortas e instrumentos ajenos al alcance de Trading Lab. No permite trasladar Sharpe, rentabilidad, comportamiento en crisis ni escalamiento de exposición a cinco monedas spot con US$500. Fuente de los autores: [artículo y resumen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum).

**Aplicación propuesta:** separar la señal “este activo tiene tendencia positiva” de “este activo está mejor clasificado que sus pares”. Son hipótesis diferentes. Ninguna autoriza futuros, cortos o apalancamiento en el laboratorio.

### 2. Momentum transversal en criptomonedas: existencia de factores, no rentabilidad de una cuenta

Liu, Tsyvinski y Wu, **Common Risk Factors in Cryptocurrency**, Journal of Finance, 2022. Su modelo usa factores de mercado, tamaño y momentum; el artículo evalúa estrategias largas/cortas asociadas a características de criptomonedas. Apoya investigar si la clasificación por momentum añade información a la exposición general al mercado. El spread entre ganadores y perdedores no es la ganancia de comprar sólo ganadores; tampoco acredita que el resultado exista en el subconjunto Bitso ni después de sus comisiones. [Artículo original, DOI y materiales de replicación](https://doi.org/10.1111/jofi.13119).

**Aplicación propuesta:** medir rendimiento incremental sobre referencias largas sencillas y exposición al mercado. No atribuir automáticamente a selección lo que puede provenir de estar más invertido durante alzas.

### 3. Extensión empírica reciente de cripto: datos y cambios de régimen importan

Borri, Liu, Tsyvinski y Wu, **Cryptocurrency as an Investable Asset Class: Coming of Age**, versión 4 del 21-mar-2026; manuscrito preparado para Annual Review of Financial Economics. Además de revisar literatura, reconstruye análisis con datos hasta septiembre de 2025, incluye monedas inactivas y compara subperiodos. Encuentra mayor relación con acciones desde 2020 y construye momentum transversal con retornos previos de dos semanas. Sus estrategias de factores son largas/cortas; precios agregados de distintos exchanges no reproducen Bitso. Su tratamiento de saltos y datos respalda investigar riesgos y calidad, no importar sus retornos. Se consultó el manuscrito, sin afirmar verificación editorial adicional. [Texto de los autores, §§2–3](https://arxiv.org/html/2510.14435v4).

**Aplicación propuesta:** revisar resultados por régimen y registrar monedas desaparecidas; no tratar el reparto 50/50 de dólares como reparto 50/50 de riesgo. No adoptar automáticamente la señal de dos semanas: aumenta otra familia de pruebas y debe superar costos locales.

### 4. Tendencia mensual larga/efectivo: regla sencilla con supuestos que hay que reemplazar

Faber, **A Quantitative Approach to Tactical Asset Allocation**, publicación inicial en 2007 y actualización del autor de febrero de 2013. Su regla mensual compara el nivel con media de diez meses y asigna a efectivo cuando pierde tendencia. El ejemplo diversifica cinco clases; usa series de retorno total y T-bills para efectivo. En p.22 declara ejecución al cierre de la señal y excluye impuestos, comisiones y slippage. Esos supuestos impiden trasladar directamente el resultado al bot. Hay que conocer primero el cierre y operar después, y no atribuir interés de T-bills al saldo cripto. [Documento original actualizado, pp.21–22](https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf).

**Aplicación propuesta:** una candidata mensual de riesgo limitado, con retorno de efectivo cero como base salvo evidencia de remuneración realmente disponible. Una mejora de drawdown no se anunciará como ganancia superior si sacrifica el resultado neto.

### 5. Contraste crítico: un buen gráfico no establece dominancia

Marmi, Pacati, Risso y Renò, **A Quantitative Approach to Faber’s Tactical Asset Allocation**, working paper, revisión de marzo de 2012. Cuestionan que los resultados de Faber constituyan una refutación de eficiencia de mercado y proponen experimentos bootstrap para evaluar estrategias. Se pudo verificar el resumen original; no se atribuyen cifras ni detalles empíricos no accesibles. Es evidencia crítica de autores que estudian esa hipótesis, no una demostración de que toda tendencia falle. [Resumen original y versión](https://doi.org/10.2139/ssrn.1476225).

**Aplicación propuesta:** comparar con una referencia sencilla y con placebos coherentes, publicar incertidumbre y permitir concluir que la muestra no distingue una mejora. Incluir esta evidencia evita seleccionar sólo publicaciones favorables.

### 6. Entrar y mantener pueden tener umbrales diferentes

Novy-Marx y Velikov, **A Taxonomy of Anomalies and Their Trading Costs**, Review of Financial Studies, 2016. Encuentran que exigir más para abrir una posición que para conservarla reduce costos eficazmente en las anomalías estudiadas. Las estrategias de mayor rotación tienen más dificultad para conservar significancia después de fricción. Su universo de acciones y costos no determina el margen correcto en Bitso; el resultado respalda la familia de histéresis, no los valores locales 15% o 4pp. [Artículo original y abstract](https://doi.org/10.1093/rfs/hhv063), [working paper de los mismos autores](https://www.nber.org/papers/w20721).

**Aplicación propuesta:** priorizar una comparación acotada de menor rotación frente al control antes de añadir indicadores. La retención no debe impedir salidas de seguridad o mantener activos inelegibles.

### 7. Actividad de negociación y resultados: advertencia empírica, no ley universal

Barber y Odean, **Trading Is Hazardous to Your Wealth**, Journal of Finance, 2000. Analizan 66,465 hogares de un broker de descuento entre 1991 y 1996: quienes más operan obtienen peores rendimientos netos que el mercado en esa muestra. Son inversores particulares en acciones, no bots de cripto actuales; el estudio no prueba que automatizar sea inútil. Sí impide asumir que más decisiones o más operaciones generan más valor. [Artículo publicado conservado por el autor](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/individual_investor_performance_final.pdf).

**Aplicación propuesta:** un control pasivo es obligatorio. El bot debe justificar tanto sus costos variables como su gasto fijo y la complejidad operacional añadida.

### 8. Selección entre pruebas: ajustar la confianza antes de elegir

Bailey y López de Prado, **The Deflated Sharpe Ratio**, Journal of Portfolio Management, 2014. El DSR aborda inflación del rendimiento aparente por selección entre múltiples pruebas y retornos no normales. Es una herramienta para controlar conclusiones después de explorar variantes; no arregla precios incorrectos, fuga temporal, universos retrospectivos ni intentos omitidos. [Publicación de los autores y resumen original](https://ssrn.com/abstract=2460551).

**Aplicación propuesta:** registrar candidatos e intentos fallidos, hacer explícita la historia ya inspeccionada y no presentar el mayor Sharpe del grid como ganador confirmado. Una corrección parcial sólo permite una afirmación parcial.

## Familias acotadas que merecen una prueba, en este orden

Estas propuestas son inferencias de diseño para Trading Lab, no instrucciones de inversión de los artículos. Todos los brazos preservan capital 500/500, posiciones largas, ausencia de deuda, señal causal, máximos de exposición y controles de riesgo. Un brazo se mide como cartera independiente; no toma capital de otro ni reparte US$1,000 adicionales entre candidatos.

| Familia | Definición inicial para preregistrar | Qué podría mejorar | Qué la refuta como mejora de rentabilidad |
|---|---|---|---|
| A. Reducir rotación de la regla vigente | Control margen 0/banda 2pp; margen 15%/banda 2pp ya registrado; dos candidatas de banda4pp con margen0 y15%. Mismas señales, universo y riesgo. | Menos sustituciones y ajustes pequeños que pagan fricción. | Ahorra costos pero empeora resultado neto o incumple riesgo/estabilidad; la ventaja desaparece con ejecución válida. |
| B. Momentum temporal lento sobre un subuniverso fijo | Dos activos, BTC y ETH, elegidos antes de medir como subuniverso sencillo ya presente en config. Al cierre mensual, mantener sólo activos con retorno propio de doce meses positivo; máximo 40% del bloque por activo, resto efectivo. Misma volatilidad máxima, frenos y salidas de riesgo. Una sola frecuencia y ventana iniciales. | Menos parámetros, menos rotación, ejecución más sencilla. | No supera a comprar/mantener el mismo subuniverso bajo riesgo y costos comparables, o sólo parece mejor por permanecer más en efectivo. |
| C. ETF con salida mensual a efectivo | Mantener como control SPY/IEF 60/40 vigente. Una candidata aplica filtro mensual de diez meses a cada asignación, dejando su parte en efectivo cuando falla; no redistribuye esa parte al ETF restante. | Posible reducción de caídas prolongadas. | El ahorro de riesgo no compensa menor resultado conforme a criterios previos, o las entradas/salidas falsas consumen la ventaja. |

**Prioridad inmediata: A**, porque mantiene comparabilidad con la inversión realizada y sólo añade una hipótesis de ejecución. B y C son candidatas posteriores, no un grid combinado. En B, “40% por activo” mantiene el tope actual; no se fuerza 50/50 completamente invertido ni se eleva la concentración permitida. Antes de proponer C formalmente, revisar que no sea una repetición de las tácticas ETF ya rechazadas en el historial; una cita externa no rescata una prueba local fallida.

Para B se necesita control pasivo del mismo subuniverso y límites, además del control vigente. Para C se necesita el 60/40 idéntico en fechas, flujos y precios. BTC y SPY aislados siguen siendo referencias descriptivas, pero no aíslan por sí solos el valor de cambiar riesgo o mantener efectivo. Comparar también retorno por unidad de exposición/riesgo; esas métricas complementan el dinero neto, no lo sustituyen.

No añadir simultáneamente RSI, MACD, múltiples medias, noticias, modelos de IA o docenas de universos. Cada decisión de ventana, frecuencia, pesos, fecha de rebalanceo o filtro cuenta como un intento. La literatura no aporta aquí evidencia suficiente para priorizar esa complejidad.

## Economía local que todas las familias deben superar

La suscripción Railway Hobby de US$5 está verificada, con uso incluido; no se suma automáticamente el consumo adicional medido mientras esté dentro del crédito del plan. Si se atribuyen US$5 mensuales íntegros al laboratorio, debe generar US$60/año después de trading sólo para pagar infraestructura: 6% de US$1,000. Cambiar las señales no reduce ese costo fijo. [Factura y lectura saneadas](../runtime-data/profitability-20261003/railway-costs.json).

El tramo inicial público Bitso USD cobra 0.30% maker o 0.36% taker por lado. Una ida/vuelta sobre US$100 de notional por lado cuesta aproximadamente US$0.60–0.72 sólo en comisiones; no se presume que la tarifa inicial dure todo el periodo ni que una orden límite se llene como maker. La evaluación debe usar tarifas disponibles por volumen, spread, slippage, rechazos y demoras. [Bitso, tabla oficial](https://bitso.com/fees), [cálculos y límites completos](PROFITABILITY_RESEARCH_20261003.md).

Una estrategia mensual puede gastar menos en trading, pero esperar en efectivo también puede perder oportunidades. Comparar ambas consecuencias. Llevar dos evaluaciones: todas las estrategias con el mismo hosting para aislar las señales; y viabilidad económica de automatizar frente a una referencia pasiva sin servicio dedicado. No mezclar esas preguntas para favorecer un brazo.

## Datos y ejecución: criterios que preceden a las curvas

1. **Universo conocido en cada fecha.** Precio de una moneda en otro exchange no demuestra que el par Bitso estuviera listado. Registrar alta, suspensión, desliste y última salida ejecutable. Los 16 activos disponibles hoy forman un universo retrospectivo; no etiquetarlo como universo histórico completo. La familia BTC/ETH reduce dimensiones, pero no elimina la obligación de documentar la decisión y disponibilidad.
2. **Ausencias y desapariciones.** No interpolar silenciosamente huecos, eliminar perdedores o asignar precio cero a una posición sin cotización. Conservar último precio identificado como obsoleto para diagnóstico y aplicar una política declarada de ejecución/valoración. Si no puede reconstruirse la liquidación, la comparación operable queda inconclusa.
3. **USD, USDC y USDT.** Documentar qué unidad representa cada serie y el par operable. No convertir una cotización USDT a USD a paridad fija sin justificarla ni confundir USD digitales con acceso bancario USD.
4. **ETF: señal y contabilidad separadas.** Retornos históricos ajustados pueden incluir dividendos/splits; no son el precio al que una orden puede llenarse. Mantener precios negociables y eventos corporativos para la ejecución, y retorno total consistente para comparar. No añadir dividendos de nuevo a una serie que ya los reinvierte.
5. **Reloj causal.** La orden ocurre después de disponer del cierre. Para ETF: siguiente sesión realmente abierta y precio de ejecución definido; para cripto: siguiente instante operable con demora y libro. Registrar calendario, zona horaria y hora de disponibilidad, no sólo fecha. La ejecución al cierre de una señal que necesita ese cierre debe tratarse como hipótesis idealizada, no como réplica real.
6. **Mínimos y redondeos con US$500.** Verificar tamaños por libro, disponibilidad fraccionaria ETF, reservas para comisiones y efectivo. Una curva de pesos continuos puede indicar operaciones que la cuenta no puede realizar.
7. **Misma lógica en bot e investigación.** Probar causalidad de prefijos, futuros perturbados, cambios del inicio de ventana y continuidad de incumbentes. El hallazgo de histéresis con historial móvil y el muestreo bootstrap defectuoso de la versión anterior se deben cerrar antes de basar una promoción en ella. [Auditoría científica actual](PROFITABILITY_RESEARCH_20261003.md).

## Cómo aceptar, refutar o dejar inconclusa una familia

Antes de correr: versión científica nueva identificada, grid pequeño, hipótesis, métricas, referencias, ventanas y costos congelados; preregistro propio anterior al código y árbol limpio conforme a [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md). Los periodos ya vistos siguen identificados; cambiarles el nombre a “fuera de muestra” no los vuelve independientes.

La aprobación necesita mejora neta y estabilidad walk-forward según umbrales fijados, placebo y bootstrap correctos, costos estresados, límites de caída y comparación prospectiva. Publicar resultado con y sin hosting, rotación, número de operaciones, exposición, peores meses, tiempo bajo máximo y sensibilidad a retrasar ejecución. El ratio de aciertos no basta: muchas pequeñas ganancias pueden ocultar una pérdida grande.

Se **refuta para promoción** una candidata que incumple cualquiera de sus gates declarados, que depende de excluir un periodo desfavorable o cuya ventaja desaparece al usar operaciones ejecutables. Se declara **inconclusa** si la calidad de datos o la muestra impide distinguirla del control. No bajar después el listón ni sustituir retorno por drawdown para declararla ganadora.

Los 28 días de paper son un mínimo operacional, no prueba suficiente de rentabilidad: para una señal mensual pueden contener sólo una decisión o ninguna transacción. Cada configuración nueva necesita su propia observación futura; no hereda días de otra. Ganar un mes o completar un calendario no sustituye la validación estadística y económica.

**Decisión de investigación:** evaluar primero el costo de la regla actual y la candidata de menor rotación; después probar, como máximo, una familia sencilla adicional a la vez. Conservar como resultado legítimo que el bot no supera una alternativa pasiva después de gastos. Este documento no activa dinero real, y no presupone que exista una estrategia rentable alcanzable mediante más pruebas.

# Procedencia del paper histórico empaquetado

> Referencia de investigación archivada. La conexión operativa vigente no necesita esta prueba ni instala la candidata rechazada. La imagen habitual usa el target `runtime`; la etapa explícita `research` queda para auditoría, fuera del workflow de entrega y del instalador operativo.


`lab.paper_comparison --plan` admite los planes v1 y v2. Sin `--attestation`
exige Git limpio y el preregistro aprobado en un commit anterior al código.
Una imagen sin `.git` usa una prueba verificable, generada antes de construirla.
El manifiesto y `--status` conservan ID, hash exacto del plan, SHA del código y
prueba completa. Una actualización del código necesita un directorio de paper
nuevo; no hereda las semanas observadas por otra versión.

Los precios prospectivos deben incluir al menos 250 cierres por activo, el último
cierre completo y ninguna ausencia desde el primer precio observado. Se permiten
ausencias anteriores al primer precio; no se rellenan huecos de calentamiento ni
de valoración. Un dato incompleto bloquea la pareja antes de simular operaciones.

Desde el checkout final limpio, después de los tests y del commit de código:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m lab.research_attestation generate \
  --plan configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --output /tmp/aggressive-v2.json
```

El destino debe ser nuevo y estar fuera del repositorio. Copiarlo al contexto
congelado como `reports/attestations/aggressive-v2.json`; nunca comprometerlo en
el mismo código cuya procedencia demuestra. El workflow operativo `gcp-image.yml` ya no recibe ese SHA ni genera pruebas experimentales. Para una auditoría separada, la etapa Docker `--target research` requiere la prueba y nunca debe instalarse como runtime operativo. No inicia paper.

Dentro de la imagen, antes de cualquier dato de mercado:

```bash
python -m lab.research_attestation verify \
  --plan /app/configs/experiments/aggressive_v2.yaml \
  --preregistration-commit 1fe6c8c586b6a9899190b4f987807daf9134846c \
  --attestation /app/reports/attestations/aggressive-v2.json
```

El runner añade ese mismo `--attestation` a `--once --plan ... --fetch` y usa un
`--data-dir` experimental dedicado. El Dockerfile fija `TRADING_LAB_BUILD_ID`
al SHA completo y `PYTHONDONTWRITEBYTECODE=1`. No reemplazar esos valores al
desplegar. La atestación se rechaza en un checkout con `.git`, donde sigue
aplicando la verificación Git normal.

La prueba incluye objetos Git commit/tree y hashes SHA-256 del inventario de
`src/`, `config.yaml`, el plan y el preregistro. El verificador comprueba los
identificadores de objetos Git, una cadena estricta de ascendencia entre
preregistro y código, los blobs de cada archivo y el frontmatter aprobado.
También rechaza fuentes añadidas, eliminadas, enlaces y bytecode no registrado.
No requiere Git, red, SciPy ni scikit-learn dentro de la imagen.

El ancla de confianza es el SHA de código elegido por el operador y la imagen
por digest registrada en la entrega. Esta prueba de contenido y ascendencia no
es una firma de tercero, no certifica cuándo se escribió una idea y no protege
contra quien controla toda la imagen y sustituye el verificador. No demuestra
rendimiento futuro, continuidad de cuatro semanas, conexión a brokers ni
autorización de dinero real. Las dependencias, Dockerfile y digest pertenecen
además a la evidencia de construcción; el inventario de la atestación cubre el
código y los artefactos del protocolo especificados arriba.

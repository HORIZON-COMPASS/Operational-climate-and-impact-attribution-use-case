# Administrative boundaries

Place a licensed Polish voivodeship shapefile here using the basename `voivodeships`:

```text
voivodeships.shp
voivodeships.shx
voivodeships.dbf
voivodeships.prj
voivodeships.cpg   # when supplied by the provider
```

The attribute table must contain a `nazwa` field with province names. The current scripts expect longitude/latitude coordinates compatible with EPSG:4326 climate grids. Verify the CRS rather than assigning EPSG:4326 to unknown geometry.

Boundary data are intentionally excluded until their provenance and redistribution licence are documented.

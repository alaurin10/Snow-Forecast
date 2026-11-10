"""The Map page's weather pictures, drawn on the server (see docs/MAP-PLAN.md).

region.py   the box the pictures cover (Web Mercator) and resampling onto it
geomet.py   Environment Canada's GeoMet: styled pictures (WMS) and raw grids (WCS)
palette.py  our colours, palette PNGs and simple compositing
grib.py     NOAA GRIB2 messages by HTTP byte range, decoded and resampled
render.py   the frames, the index the browser reads, and pruning
sources/    one module per upstream
"""

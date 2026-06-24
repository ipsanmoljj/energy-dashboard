FROM rocker/r-ver:4.4

RUN apt-get update && apt-get install -y \
    libssl-dev libcurl4-openssl-dev libxml2-dev libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

# Binary packages from Posit Package Manager — much faster than source
RUN Rscript -e "\
  options(repos = c(CRAN = 'https://packagemanager.posit.co/cran/__linux__/bookworm/latest')); \
  install.packages(c('plumber','jsonlite','data.table','lubridate','zoo', \
                     'strucchange','KFAS','MSwM','forecast','quantmod'))"

WORKDIR /app
COPY . .

RUN mkdir -p output/CL output/LCO output/HO output/LGO

EXPOSE 8001

CMD ["Rscript", "start.R"]

terraform {
  backend "gcs" {
    bucket = "fgm9000-portfolio-tfstate"
    prefix = "ga4-sql-analyst"
  }
}

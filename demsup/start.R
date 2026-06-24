port <- as.integer(Sys.getenv("PORT", "8001"))
cat(sprintf("Starting demsup plumber on port %d\n", port))
plumber::pr_run(plumber::pr("plumber.R"), host = "0.0.0.0", port = port)

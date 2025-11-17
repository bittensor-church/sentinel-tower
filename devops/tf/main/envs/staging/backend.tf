terraform {
  backend "s3" {
    bucket = "bittensor_sentinel-awgkkh"
    key    = "staging/main.tfstate"
    region = "us-east-1"
  }
}

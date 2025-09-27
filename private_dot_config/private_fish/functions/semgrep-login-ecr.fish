function semgrep-login-ecr
    # Set REGION to the first argument or default to "us-west-2"
    set -l REGION $argv[1]
    if test -z "$REGION"
        set REGION us-west-2
    end
    aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "338683922796.dkr.ecr.$REGION.amazonaws.com"
end

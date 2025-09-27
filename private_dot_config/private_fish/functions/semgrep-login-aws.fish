function semgrep-login-aws
    aws sso login --sso-session semgrep
    set -x AWS_PROFILE engineer
end

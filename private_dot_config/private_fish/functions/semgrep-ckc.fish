function semgrep-ckc
    if test (count $argv) -eq 0
        echo "Usage: ckc dev2|staging|prod [namespace]"
        echo "Current context: (kubectl config current-context)"
        return 1
    end

    switch $argv[1]
        case dev2
            aws eks --region us-west-2 update-kubeconfig --name dev2-semgrep-app-cluster --role-arn arn:aws:iam::338683922796:role/dev2-semgrep-app-cluster-kubernetes-apply
        case staging
            aws eks --region us-west-2 update-kubeconfig --name staging-semgrep-app-cluster --role-arn arn:aws:iam::338683922796:role/staging-semgrep-app-cluster-kubernetes-apply
        case prod
            aws eks --region us-west-2 update-kubeconfig --name prod-semgrep-app-cluster --role-arn arn:aws:iam::338683922796:role/prod-semgrep-app-cluster-kubernetes-apply
        case '*'
            echo "unknown cluster '$argv[1]'"
            return 1
    end

    if test -n "$argv[2]"
        kubectl config set-context --current --namespace $argv[2]
    end
end

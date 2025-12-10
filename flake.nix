{
  description = "A development environment for the Ista Calista Home Assistant component.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Reference the home-assistant derivation from nixpkgs. This is our foundation.
        ha = pkgs.home-assistant;

        # Define our custom component's dependency in the context of Home Assistant's
        # Python environment. This is the key to avoiding conflicts.
        pycalista-ista-for-ha = ha.python.pkgs.buildPythonPackage rec {
          pname = "pycalista-ista";
          version = "0.7.0";
          format = "pyproject";

          src = pkgs.fetchFromGitHub {
            owner = "herruzo99";
            repo = "pycalista-ista";
            rev = "v${version}";
            hash = "sha256-R15btoGZaymU2PR1P9NxyXkpJXd3vy4RaSHTKGWLb+Y=";
          };

          # All dependencies are now drawn from `ha.python.pkgs`, ensuring consistency.
          propagatedBuildInputs = with ha.python.pkgs; [
            setuptools
            aiohttp
            beautifulsoup4
            lxml
            requests
            pandas
            xlrd
            unidecode
          ];

          pythonImportsCheck = [ "pycalista_ista" ];
        };

        # Build the final test environment using the exact Python provided by the
        # home-assistant derivation.
        pythonTestEnv = ha.python.withPackages (ps: with ps; [
          # Test dependencies, all sourced from the consistent HA package set.
          pytest
          pytest-cov
          pytest-homeassistant-custom-component
          aioresponses
          freezegun
          ruff
          isort
          black

          # Add our consistently-built package to the environment.
          pycalista-ista-for-ha
        ]);

      in
      {
        # The primary development shell.
        devShells.default = pkgs.mkShell {
          name = "ista-calista-dev";

          packages = [
            pythonTestEnv
            pkgs.pre-commit
          ];

          shellHook = ''
            # Add the project's custom_components directory to the PYTHONPATH.
            # This is crucial for pytest to discover the integration's code.
            export PYTHONPATH="$PWD/custom_components:$PYTHONPATH"

            if [ -f .pre-commit-config.yaml ]; then
              pre-commit install -f --install-hooks
            fi

            echo ""
            echo "----------------------------------------------------------"
            echo "  Nix dev shell for ista_calista is activated."
            echo ""
            echo "  To run tests, execute: pytest"
            echo "----------------------------------------------------------"
            echo ""
          '';
        };
      });
}
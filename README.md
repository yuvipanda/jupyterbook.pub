# Welcome to jupyterbook.pub (name tbd)

## Why?

When you are using JupyterBook, I think of three distinct activities (roughly speaking):

1. Authoring (you're writing your content, iterating on it)
1. Publishing (your *source* content is pushed somewhere like GitHub, Zenodo, etc)
1. Rendering (your *source* content is rendered into something more human readable, via GitHub Pages, Netlify, etc)

(3) feels like *accidental complexity*, as it forces you to understand and deal with things that are not core to the
process of writing. The goal of this project is to reduce this accidental complexity to 0 as much as possible, and
then see what additional possible things can be built on top of this.

## Design

At a high level, JupyterBook.Pub has two separate features:
1. Content fetching
2. Content building

(1) is handled by [repoproviders](https://github.com/yuvipanda/repoproviders). (2) is
ultimately implemented via an executor abstraction.

To implement a builder, one simply needs to define a class with a callable `entrypoint` that builds a commandline. The entrypoint maps three well-defined concepts onto a set of commandline arguments:
1. Source directory
2. Build directory
3. Configuration file

Each executor (docker, Kubernetes, local process) is designed to call this entrypoint,
managing details like volume mounts, remote execution, etc.

Custom builders can be used by creating an importable class that defines this
entrypoint. 

## Copyright

- Copyright © 2026 Yuvi.
- Free software distributed under the [3-Clause BSD License](./LICENSE).

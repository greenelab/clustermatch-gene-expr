#pragma once

#include <vector>

template <typename T>
std::vector<T> cudaAri(int* parts, const size_t n_features, const size_t n_parts, const size_t n_objs);

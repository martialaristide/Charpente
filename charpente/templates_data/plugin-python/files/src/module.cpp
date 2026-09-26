#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <numeric>
#include <string>
#include <vector>

namespace py = pybind11;

static double mean(const std::vector<double>& values) {
    if (values.empty()) throw std::invalid_argument("mean of an empty list");
    return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
}

PYBIND11_MODULE(@IDENT@, m) {
    m.doc() = "@TITLE@: C++ functions for Python";
    m.def("add", [](int a, int b) { return a + b; }, "Add two integers", py::arg("a"), py::arg("b"));
    m.def("mean", &mean, "Mean of a list of numbers");
    m.def("shout", [](const std::string& s) { return s + "!"; }, "Append an exclamation mark");
}

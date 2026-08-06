// A 10mm cube with no lid: five faces where a solid needs six.
//
// Deliberately unsound input. Every measurement library will still hand you a
// volume for this — 500 rather than 1000, computed over a surface that does not
// enclose anything — which is the case partspec must refuse rather than answer.
polyhedron(
  points = [
    [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
    [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10]
  ],
  faces = [
    [0, 1, 2], [0, 2, 3],  // floor
    [0, 4, 5], [0, 5, 1],  // walls
    [1, 5, 6], [1, 6, 2],
    [2, 6, 7], [2, 7, 3],
    [3, 7, 4], [3, 4, 0]
    // no lid
  ]
);

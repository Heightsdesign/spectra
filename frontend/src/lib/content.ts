export const categories = [
  { number: "01", title: "Centering", description: "The balance of the printed image within the card’s physical boundaries." },
  { number: "02", title: "Corners", description: "The condition and consistency of each corner, considered individually." },
  { number: "03", title: "Edges", description: "The integrity of the perimeter, including visible wear and irregularities." },
  { number: "04", title: "Surface", description: "The condition of the front and back, including visible marks and defects." },
] as const;

export const steps = [
  { number: "01", title: "Prepare", description: "Review the eligible cards and preparation guidance when these are published." },
  { number: "02", title: "Submit", description: "Create a submission and arrange delivery once online submissions open." },
  { number: "03", title: "Assessment", description: "The planned workflow combines computer-assisted analysis with human validation." },
  { number: "04", title: "Return", description: "Packaging, certificate access and return options will be detailed before launch." },
] as const;
